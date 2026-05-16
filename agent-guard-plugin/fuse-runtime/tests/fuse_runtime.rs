use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::thread::sleep;
use std::time::Duration;

use sha2::{Digest, Sha256};
use tempfile::TempDir;

fn derive_state_id(root: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(
        root.canonicalize()
            .unwrap_or_else(|_| root.to_path_buf())
            .to_string_lossy()
            .as_bytes(),
    );
    let digest = hasher.finalize();
    let hex = format!("{:x}", digest);
    hex[..32].to_string()
}

fn managed_path(home: &Path, root: &Path, name: &str) -> PathBuf {
    home.join(".agent-guard-fuse")
        .join("managed")
        .join(derive_state_id(root))
        .join(name)
}

fn lock_file(home: &Path) -> PathBuf {
    home.join(".agent-guard-fuse").join("lock.json")
}

fn write_lock(home: &Path, root: &Path, token: &str, files: &[&str]) {
    let path = lock_file(home);
    fs::create_dir_all(path.parent().expect("lock parent")).expect("create lock dir");
    let files_json = files
        .iter()
        .map(|item| format!("\"{item}\""))
        .collect::<Vec<_>>()
        .join(",");
    fs::write(
        path,
        format!(
            "{{\"version\":3,\"roots\":{{\"{}\":{{\"managed\":\"{}\",\"token\":\"{}\",\"files\":[{}]}}}}}}",
            root.canonicalize()
                .unwrap_or_else(|_| root.to_path_buf())
                .display(),
            home.join(".agent-guard-fuse")
                .join("managed")
                .join(derive_state_id(root))
                .display(),
            token,
            files_json
        ),
    )
    .expect("write lock file");
}

fn runtime_bin() -> &'static str {
    env!("CARGO_BIN_EXE_agent-guard-fuse")
}

fn spawn_mount(home: &Path, root: &Path) -> Child {
    Command::new(runtime_bin())
        .arg("mount")
        .arg("--root")
        .arg(root)
        .env("HOME", home)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn mount process")
}

fn timed_read(path: &Path) -> Output {
    Command::new("timeout")
        .arg("2")
        .arg("cat")
        .arg(path)
        .output()
        .expect("run timed read")
}

fn timed_write(path: &Path, data: &str) -> Output {
    Command::new("timeout")
        .arg("2")
        .arg("python3")
        .arg("-c")
        .arg("from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])")
        .arg(path)
        .arg(data)
        .output()
        .expect("run timed write")
}

fn timed_delete(path: &Path) -> Output {
    Command::new("timeout")
        .arg("2")
        .arg("python3")
        .arg("-c")
        .arg("import os, sys; os.remove(sys.argv[1])")
        .arg(path)
        .output()
        .expect("run timed delete")
}

fn timed_mkdir(path: &Path) -> Output {
    Command::new("timeout")
        .arg("2")
        .arg("mkdir")
        .arg("-p")
        .arg(path)
        .output()
        .expect("run timed mkdir")
}

fn run_unmount(home: &Path, root: &Path) {
    let status = Command::new(runtime_bin())
        .arg("unmount")
        .arg("--root")
        .arg(root)
        .env("HOME", home)
        .status()
        .expect("run unmount command");
    assert!(status.success(), "unmount command failed: {status}");
}

fn setup(name: &str, content: &str) -> (TempDir, TempDir, PathBuf, PathBuf, Child) {
    let root = tempfile::tempdir().expect("create root tempdir");
    let home = tempfile::tempdir().expect("create home tempdir");
    let managed = managed_path(home.path(), root.path(), name);
    fs::create_dir_all(managed.parent().expect("managed parent")).expect("create managed dir");
    fs::write(&managed, content).expect("seed managed file");

    let child = spawn_mount(home.path(), root.path());
    let public = root.path().join(".agent").join(name);
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while std::time::Instant::now() < deadline {
        if public.exists() {
            break;
        }
        sleep(Duration::from_millis(50));
    }
    (root, home, public, managed, child)
}

#[test]
fn mounted_runtime_reads_managed_content_and_requires_lock_for_writes() {
    let (root, home, mount_path, managed, mut child) = setup("state.json", "{\"stage\":\"IDLE\"}\n");

    let read = timed_read(&mount_path);
    assert!(
        read.status.success(),
        "read failed: status={:?} stderr={}",
        read.status.code(),
        String::from_utf8_lossy(&read.stderr)
    );
    assert_eq!(String::from_utf8_lossy(&read.stdout), "{\"stage\":\"IDLE\"}\n");

    let open_write = timed_write(&mount_path, "{\"stage\":\"VERIFY\"}\n");
    assert!(open_write.status.success(), "unlocked direct write should succeed");

    write_lock(home.path(), root.path(), "token-1", &["state.json"]);
    let denied = timed_write(&mount_path, "{\"stage\":\"REVIEW\"}\n");
    assert!(!denied.status.success(), "locked direct write unexpectedly succeeded");

    fs::write(lock_file(home.path()), format!(
        "{{\"version\":3,\"roots\":{{\"{}\":{{\"managed\":\"{}\",\"token\":\"token-1\",\"files\":[]}}}}}}",
        root.path().canonicalize().unwrap_or_else(|_| root.path().to_path_buf()).display(),
        home.path().join(".agent-guard-fuse").join("managed").join(derive_state_id(root.path())).display()
    )).expect("unlock file by clearing files");
    let allowed_again = timed_write(&mount_path, "{\"stage\":\"VERIFY\"}\n");
    assert!(allowed_again.status.success(), "direct write after unlock should succeed");
    assert_eq!(
        fs::read_to_string(&managed).expect("read managed file"),
        "{\"stage\":\"VERIFY\"}\n"
    );

    run_unmount(home.path(), root.path());
    let status = child.wait().expect("wait on mount child");
    assert!(status.success(), "mount child exited unsuccessfully: {status}");
}

#[test]
fn mounted_runtime_requires_lock_for_delete_on_public_path() {
    let (root, home, mount_path, managed, mut child) = setup("plan.yaml", "steps: []\n");

    let unlocked_delete = timed_delete(&mount_path);
    assert!(unlocked_delete.status.success(), "unlocked delete should succeed");
    fs::write(&managed, "steps: []\n").expect("restore managed file");

    write_lock(home.path(), root.path(), "token-2", &["plan.yaml"]);
    let denied = timed_delete(&mount_path);
    assert!(!denied.status.success(), "locked delete unexpectedly succeeded");

    fs::write(lock_file(home.path()), format!(
        "{{\"version\":3,\"roots\":{{\"{}\":{{\"managed\":\"{}\",\"token\":\"token-2\",\"files\":[]}}}}}}",
        root.path().canonicalize().unwrap_or_else(|_| root.path().to_path_buf()).display(),
        home.path().join(".agent-guard-fuse").join("managed").join(derive_state_id(root.path())).display()
    )).expect("unlock file by clearing files");
    let deleted = timed_delete(&mount_path);
    assert!(deleted.status.success(), "direct delete after unlock should succeed");
    assert!(!managed.exists());

    run_unmount(home.path(), root.path());
    let status = child.wait().expect("wait on mount child");
    assert!(status.success(), "mount child exited unsuccessfully: {status}");
}

#[test]
fn mounted_runtime_allows_passthrough_directories_and_files_without_token() {
    let (root, home, _public, _managed, mut child) = setup("state.json", "{\"stage\":\"IDLE\"}\n");
    let mount_dir = root.path().join(".agent");
    let artifacts_dir = mount_dir.join("artifacts");
    let note_file = mount_dir.join("events.jsonl");

    let mkdir_result = timed_mkdir(&artifacts_dir);
    assert!(
        mkdir_result.status.success(),
        "mkdir failed: status={:?} stderr={}",
        mkdir_result.status.code(),
        String::from_utf8_lossy(&mkdir_result.stderr)
    );

    let write_result = timed_write(&note_file, "{\"event\":\"ok\"}\n");
    assert!(
        write_result.status.success(),
        "passthrough write failed: status={:?} stderr={}",
        write_result.status.code(),
        String::from_utf8_lossy(&write_result.stderr)
    );

    assert!(root.path().join(".agent").join("artifacts").is_dir());
    assert_eq!(
        fs::read_to_string(managed_path(home.path(), root.path(), "events.jsonl"))
            .expect("read managed passthrough file"),
        "{\"event\":\"ok\"}\n"
    );

    run_unmount(home.path(), root.path());
    let status = child.wait().expect("wait on mount child");
    assert!(status.success(), "mount child exited unsuccessfully: {status}");
}
