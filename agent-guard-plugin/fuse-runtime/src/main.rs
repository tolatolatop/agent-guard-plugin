use clap::{Parser, Subcommand};
use filetime::{set_file_mtime, FileTime};
use fuser::{
    FileAttr, FileType, Filesystem, MountOption, ReplyAttr, ReplyCreate, ReplyData, ReplyDirectory,
    ReplyEmpty, ReplyEntry, ReplyOpen, ReplyWrite, Request,
};
use libc::{EACCES, ENOENT, EPERM};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap};
use std::ffi::OsStr;
use std::fs::{self, DirBuilder, File, OpenOptions};
use std::os::unix::fs::{DirBuilderExt, FileExt, MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::process::Command;
#[cfg(test)]
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime};

const TTL: Duration = Duration::from_secs(1);
const ROOT_INO: u64 = 1;

#[derive(Parser)]
#[command(name = "agent-guard-fuse")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    Mount { #[arg(long)] root: PathBuf },
    Unmount { #[arg(long)] root: PathBuf },
}

#[derive(Debug, Deserialize, Serialize)]
struct LockFile {
    #[allow(dead_code)]
    version: u32,
    #[serde(default)]
    roots: HashMap<String, RootLock>,
}

#[derive(Debug, Deserialize, Serialize, Default, Clone)]
struct RootLock {
    #[serde(default)]
    managed: String,
    #[serde(default)]
    token: String,
    #[serde(default)]
    files: Vec<String>,
}

#[derive(Clone)]
struct WorkspaceMount {
    home: PathBuf,
    root: PathBuf,
}

impl WorkspaceMount {
    fn new(root: PathBuf, home: PathBuf) -> Self {
        Self { home, root }
    }

    fn root_key(&self) -> String {
        normalize_root_path(&self.root)
    }

    fn state_id(&self) -> String {
        derive_state_id(&self.root)
    }

    fn mount_dir(&self) -> PathBuf {
        self.root.join(".agent")
    }

    fn lock_file(&self) -> PathBuf {
        self.home.join(".agent-guard-fuse").join("lock.json")
    }

    fn public_path(&self, name: &str) -> PathBuf {
        self.mount_dir().join(name)
    }

    fn managed_root(&self, lock_file: &LockFile) -> PathBuf {
        if let Some(entry) = lock_file.roots.get(&self.root_key()) {
            if !entry.managed.is_empty() {
                return PathBuf::from(&entry.managed);
            }
        }
        self.home.join(".agent-guard-fuse").join("managed").join(self.state_id())
    }
}

struct GuardFs {
    workspace: WorkspaceMount,
    ino_to_rel: HashMap<u64, PathBuf>,
    rel_to_ino: HashMap<PathBuf, u64>,
    next_ino: u64,
}

impl GuardFs {
    fn new(root: PathBuf, home: PathBuf) -> Self {
        let mut ino_to_rel = HashMap::new();
        let mut rel_to_ino = HashMap::new();
        ino_to_rel.insert(ROOT_INO, PathBuf::new());
        rel_to_ino.insert(PathBuf::new(), ROOT_INO);
        Self {
            workspace: WorkspaceMount::new(root, home),
            ino_to_rel,
            rel_to_ino,
            next_ino: 10,
        }
    }

    fn for_root(root: PathBuf) -> Self {
        Self::new(root, home_dir())
    }

    fn lock_file(&self) -> PathBuf {
        self.workspace.lock_file()
    }

    fn public_path(&self, name: &str) -> PathBuf {
        self.workspace.public_path(name)
    }

    fn managed_root(&self) -> PathBuf {
        self.workspace.managed_root(&self.load_locks())
    }

    fn root_lock(&self) -> Option<RootLock> {
        self.load_locks().roots.get(&self.workspace.root_key()).cloned()
    }

    fn locked_files(&self) -> Vec<String> {
        self.root_lock()
            .map(|entry| entry.files)
            .unwrap_or_default()
    }

    fn is_locked_rel(&self, rel: &Path) -> bool {
        if rel.components().count() != 1 {
            return false;
        }
        let Some(name) = rel.file_name().and_then(|item| item.to_str()) else {
            return false;
        };
        self.locked_files().iter().any(|item| item == name)
    }

    fn visible_root_entries(&self) -> Vec<String> {
        let mut names = BTreeSet::new();
        if let Ok(entries) = fs::read_dir(self.managed_root()) {
            for entry in entries.flatten() {
                names.insert(entry.file_name().to_string_lossy().to_string());
            }
        }
        names.into_iter().collect()
    }

    fn child_rel(&self, parent: &Path, name: &OsStr) -> PathBuf {
        if parent.as_os_str().is_empty() {
            PathBuf::from(name)
        } else {
            parent.join(name)
        }
    }

    fn rel_for_ino(&self, ino: u64) -> Option<PathBuf> {
        self.ino_to_rel.get(&ino).cloned()
    }

    fn ensure_ino(&mut self, rel: &Path) -> u64 {
        if let Some(existing) = self.rel_to_ino.get(rel) {
            return *existing;
        }
        let ino = self.next_ino;
        self.next_ino += 1;
        let rel_buf = rel.to_path_buf();
        self.rel_to_ino.insert(rel_buf.clone(), ino);
        self.ino_to_rel.insert(ino, rel_buf);
        ino
    }

    fn backing_path(&self, rel: &Path) -> PathBuf {
        if rel.as_os_str().is_empty() {
            self.managed_root()
        } else {
            self.managed_root().join(rel)
        }
    }

    fn file_attr_for_rel(&mut self, rel: &Path) -> Result<FileAttr, i32> {
        if rel.as_os_str().is_empty() {
            return Ok(self.root_attr());
        }
        let path = self.backing_path(rel);
        let meta = path.metadata().map_err(|_| ENOENT)?;
        let kind = if meta.is_dir() {
            FileType::Directory
        } else {
            FileType::RegularFile
        };
        Ok(FileAttr {
            ino: self.ensure_ino(rel),
            size: meta.size(),
            blocks: meta.blocks(),
            atime: SystemTime::UNIX_EPOCH + Duration::from_secs(meta.atime() as u64),
            mtime: SystemTime::UNIX_EPOCH + Duration::from_secs(meta.mtime() as u64),
            ctime: SystemTime::UNIX_EPOCH + Duration::from_secs(meta.ctime() as u64),
            crtime: SystemTime::UNIX_EPOCH,
            kind,
            perm: if meta.is_dir() { 0o755 } else { 0o644 },
            nlink: if meta.is_dir() { 2 } else { 1 },
            uid: meta.uid(),
            gid: meta.gid(),
            rdev: 0,
            blksize: meta.blksize() as u32,
            flags: 0,
        })
    }

    fn load_locks(&self) -> LockFile {
        let lock_path = self.lock_file();
        if !lock_path.exists() {
            return LockFile { version: 3, roots: HashMap::new() };
        }
        let text = fs::read_to_string(lock_path)
            .unwrap_or_else(|_| "{\"version\":3,\"roots\":{}}".to_string());
        serde_json::from_str(&text).unwrap_or(LockFile {
            version: 3,
            roots: HashMap::new(),
        })
    }

    fn is_unlocked_for_write(&self, rel: &Path) -> bool {
        let locked = self.is_locked_rel(rel);
        if locked {
            let name = rel.file_name().and_then(|item| item.to_str()).unwrap_or_default();
            debug_log(format!(
                "deny direct write root={} public={} file={} because it is locked",
                self.workspace.root_key(),
                self.public_path(name).display(),
                name
            ));
        }
        locked
    }

    fn root_attr(&self) -> FileAttr {
        let now = SystemTime::now();
        FileAttr {
            ino: ROOT_INO,
            size: 0,
            blocks: 0,
            atime: now,
            mtime: now,
            ctime: now,
            crtime: now,
            kind: FileType::Directory,
            perm: 0o755,
            nlink: 2,
            uid: unsafe { libc::geteuid() },
            gid: unsafe { libc::getegid() },
            rdev: 0,
            blksize: 4096,
            flags: 0,
        }
    }
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/"))
}

fn derive_state_id(root: &Path) -> String {
    let mut hasher = Sha256::new();
    hasher.update(root.canonicalize().unwrap_or_else(|_| root.to_path_buf()).to_string_lossy().as_bytes());
    let digest = hasher.finalize();
    let hex = format!("{:x}", digest);
    hex[..32].to_string()
}

fn normalize_root_path(root: &Path) -> String {
    root.canonicalize()
        .unwrap_or_else(|_| root.to_path_buf())
        .to_string_lossy()
        .to_string()
}

fn debug_log(message: impl AsRef<str>) {
    if std::env::var_os("AGENT_GUARD_FUSE_DEBUG").is_some() {
        eprintln!("[agent-guard-fuse] {}", message.as_ref());
    }
}

fn save_locks(lock_path: &Path, payload: &LockFile) -> std::io::Result<()> {
    if let Some(parent) = lock_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let body = serde_json::to_string_pretty(payload)
        .map_err(|err| std::io::Error::new(std::io::ErrorKind::Other, err.to_string()))?;
    fs::write(lock_path, format!("{body}\n"))
}

fn ensure_root_lock_entry(fs_view: &GuardFs) -> std::io::Result<()> {
    let root_key = fs_view.workspace.root_key();
    let mut payload = fs_view.load_locks();
    if payload.roots.contains_key(&root_key) {
        return Ok(());
    }
    payload.roots.insert(
        root_key,
        RootLock {
            managed: fs_view.managed_root().to_string_lossy().to_string(),
            token: String::new(),
            files: Vec::new(),
        },
    );
    save_locks(&fs_view.lock_file(), &payload)
}

fn file_mtime(path: &Path) -> Option<FileTime> {
    path.metadata()
        .ok()
        .map(|meta| FileTime::from_last_modification_time(&meta))
}

fn copy_file_with_mtime(source: &Path, target: &Path) -> std::io::Result<()> {
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::copy(source, target)?;
    if let Some(mtime) = file_mtime(source) {
        let _ = set_file_mtime(target, mtime);
    }
    Ok(())
}

fn sync_file_pair(left: &Path, right: &Path) -> std::io::Result<()> {
    let left_exists = left.is_file();
    let right_exists = right.is_file();
    match (left_exists, right_exists) {
        (false, false) => Ok(()),
        (true, false) => copy_file_with_mtime(left, right),
        (false, true) => copy_file_with_mtime(right, left),
        (true, true) => {
            let left_mtime = file_mtime(left);
            let right_mtime = file_mtime(right);
            match (left_mtime, right_mtime) {
                (Some(lhs), Some(rhs)) if lhs > rhs => copy_file_with_mtime(left, right),
                (Some(lhs), Some(rhs)) if rhs > lhs => copy_file_with_mtime(right, left),
                _ => {
                    let left_bytes = fs::read(left)?;
                    let right_bytes = fs::read(right)?;
                    if left_bytes != right_bytes {
                        copy_file_with_mtime(right, left)?;
                    }
                    Ok(())
                }
            }
        }
    }
}

fn clear_directory(dir: &Path) -> std::io::Result<()> {
    if !dir.exists() {
        return Ok(());
    }
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            fs::remove_dir_all(path)?;
        } else {
            fs::remove_file(path)?;
        }
    }
    Ok(())
}

fn restore_tree(source: &Path, target: &Path) -> std::io::Result<()> {
    if !source.exists() {
        return Ok(());
    }
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        if source_path.is_dir() {
            fs::create_dir_all(&target_path)?;
            restore_tree(&source_path, &target_path)?;
            continue;
        }
        copy_file_with_mtime(&source_path, &target_path)?;
    }
    Ok(())
}

fn sync_trees(public: &Path, managed: &Path) -> std::io::Result<()> {
    let public_exists = public.exists();
    let managed_exists = managed.exists();
    match (public_exists, managed_exists) {
        (false, false) => return Ok(()),
        (false, true) => {
            if managed.is_dir() {
                fs::create_dir_all(public)?;
                return restore_tree(managed, public);
            }
            return copy_file_with_mtime(managed, public);
        }
        (true, false) => {
            if public.is_dir() {
                fs::create_dir_all(managed)?;
                return restore_tree(public, managed);
            }
            return copy_file_with_mtime(public, managed);
        }
        (true, true) => {}
    }

    let public_meta = public.metadata()?;
    let managed_meta = managed.metadata()?;
    if public_meta.is_file() && managed_meta.is_file() {
        return sync_file_pair(public, managed);
    }
    if public_meta.is_dir() && managed_meta.is_dir() {
        let mut names = BTreeSet::new();
        for entry in fs::read_dir(public)? {
            names.insert(entry?.file_name());
        }
        for entry in fs::read_dir(managed)? {
            names.insert(entry?.file_name());
        }
        for name in names {
            sync_trees(&public.join(&name), &managed.join(&name))?;
        }
        return Ok(());
    }

    let public_time = FileTime::from_last_modification_time(&public_meta);
    let managed_time = FileTime::from_last_modification_time(&managed_meta);
    if public_time > managed_time {
        if managed_meta.is_dir() {
            fs::remove_dir_all(managed)?;
        } else {
            fs::remove_file(managed)?;
        }
        if public_meta.is_dir() {
            fs::create_dir_all(managed)?;
            restore_tree(public, managed)?;
        } else {
            copy_file_with_mtime(public, managed)?;
        }
        return Ok(());
    }

    if public_meta.is_dir() {
        fs::remove_dir_all(public)?;
    } else {
        fs::remove_file(public)?;
    }
    if managed_meta.is_dir() {
        fs::create_dir_all(public)?;
        restore_tree(managed, public)?;
    } else {
        copy_file_with_mtime(managed, public)?;
    }
    Ok(())
}

impl Filesystem for GuardFs {
    fn lookup(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, reply: ReplyEntry) {
        debug_log(format!("lookup parent={parent} name={}", name.to_string_lossy()));
        let Some(parent_rel) = self.rel_for_ino(parent) else {
            reply.error(ENOENT);
            return;
        };
        let child_rel = self.child_rel(&parent_rel, name);
        match self.file_attr_for_rel(&child_rel) {
            Ok(attr) => reply.entry(&TTL, &attr, 0),
            Err(code) => reply.error(code),
        }
    }

    fn getattr(&mut self, _req: &Request<'_>, ino: u64, _fh: Option<u64>, reply: ReplyAttr) {
        debug_log(format!("getattr ino={ino}"));
        let Some(rel) = self.rel_for_ino(ino) else {
            reply.error(ENOENT);
            return;
        };
        match self.file_attr_for_rel(&rel) {
            Ok(attr) => reply.attr(&TTL, &attr),
            Err(code) => reply.error(code),
        }
    }

    fn readdir(&mut self, _req: &Request<'_>, ino: u64, _fh: u64, offset: i64, mut reply: ReplyDirectory) {
        debug_log(format!("readdir ino={ino} offset={offset}"));
        let Some(rel) = self.rel_for_ino(ino) else {
            reply.error(ENOENT);
            return;
        };
        let backing = self.backing_path(&rel);
        if !backing.is_dir() {
            reply.error(ENOENT);
            return;
        }

        let mut entries: Vec<(u64, FileType, String)> = Vec::new();
        let parent_rel = rel.parent().unwrap_or(Path::new("")).to_path_buf();
        entries.push((self.ensure_ino(&rel), FileType::Directory, ".".to_string()));
        entries.push((self.ensure_ino(&parent_rel), FileType::Directory, "..".to_string()));

        let names: Vec<String> = if rel.as_os_str().is_empty() {
            self.visible_root_entries()
        } else {
            match fs::read_dir(&backing) {
                Ok(items) => items
                    .flatten()
                    .map(|entry| entry.file_name().to_string_lossy().to_string())
                    .collect(),
                Err(_) => {
                    reply.error(ENOENT);
                    return;
                }
            }
        };

        for name in names {
            let child_rel = self.child_rel(&rel, OsStr::new(&name));
            if let Ok(attr) = self.file_attr_for_rel(&child_rel) {
                entries.push((attr.ino, attr.kind, name));
            }
        }

        for (index, entry) in entries.iter().enumerate().skip(offset as usize) {
            if reply.add(entry.0, (index + 1) as i64, entry.1, entry.2.as_str()) {
                break;
            }
        }
        reply.ok();
    }

    fn open(&mut self, _req: &Request<'_>, ino: u64, flags: i32, reply: ReplyOpen) {
        debug_log(format!("open ino={ino} flags={flags}"));
        let Some(rel) = self.rel_for_ino(ino) else {
            reply.error(ENOENT);
            return;
        };
        let path = self.backing_path(&rel);
        if path.is_dir() {
            reply.error(libc::EISDIR);
            return;
        }
        let writable = flags & (libc::O_WRONLY | libc::O_RDWR | libc::O_TRUNC | libc::O_APPEND) != 0;
        if writable && self.is_unlocked_for_write(&rel) {
            reply.error(EACCES);
            return;
        }
        reply.opened(0, flags as u32);
    }

    fn read(&mut self, _req: &Request<'_>, ino: u64, _fh: u64, offset: i64, size: u32, _flags: i32, _lock_owner: Option<u64>, reply: ReplyData) {
        debug_log(format!("read ino={ino} offset={offset} size={size}"));
        let Some(rel) = self.rel_for_ino(ino) else {
            reply.error(ENOENT);
            return;
        };
        let path = self.backing_path(&rel);
        let file = match File::open(path) {
            Ok(file) => file,
            Err(_) => {
                reply.error(ENOENT);
                return;
            }
        };
        let mut buffer = vec![0; size as usize];
        match file.read_at(&mut buffer, offset as u64) {
            Ok(read_len) => reply.data(&buffer[..read_len]),
            Err(_) => reply.error(ENOENT),
        }
    }

    fn write(&mut self, _req: &Request<'_>, ino: u64, _fh: u64, offset: i64, data: &[u8], _write_flags: u32, _flags: i32, _lock_owner: Option<u64>, reply: ReplyWrite) {
        debug_log(format!("write ino={ino} offset={offset} len={}", data.len()));
        let Some(rel) = self.rel_for_ino(ino) else {
            reply.error(ENOENT);
            return;
        };
        if self.is_unlocked_for_write(&rel) {
            reply.error(EACCES);
            return;
        }
        let path = self.backing_path(&rel);
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let file = match OpenOptions::new().write(true).create(true).mode(0o644).open(path) {
            Ok(file) => file,
            Err(_) => {
                reply.error(ENOENT);
                return;
            }
        };
        match file.write_at(data, offset as u64) {
            Ok(written) => reply.written(written as u32),
            Err(_) => reply.error(EACCES),
        }
    }

    fn create(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, mode: u32, _umask: u32, flags: i32, reply: ReplyCreate) {
        debug_log(format!("create parent={parent} name={} mode={mode:o} flags={flags}", name.to_string_lossy()));
        let Some(parent_rel) = self.rel_for_ino(parent) else {
            reply.error(ENOENT);
            return;
        };
        let child_rel = self.child_rel(&parent_rel, name);
        if self.is_unlocked_for_write(&child_rel) {
            reply.error(EACCES);
            return;
        }
        let path = self.backing_path(&child_rel);
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        match OpenOptions::new().create(true).write(true).mode(mode).open(&path) {
            Ok(_) => match self.file_attr_for_rel(&child_rel) {
                Ok(attr) => reply.created(&TTL, &attr, 0, 0, flags as u32),
                Err(code) => reply.error(code),
            },
            Err(_) => reply.error(EACCES),
        }
    }

    fn mknod(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, mode: u32, _umask: u32, _rdev: u32, reply: ReplyEntry) {
        debug_log(format!("mknod parent={parent} name={} mode={mode:o}", name.to_string_lossy()));
        let Some(parent_rel) = self.rel_for_ino(parent) else {
            reply.error(ENOENT);
            return;
        };
        let child_rel = self.child_rel(&parent_rel, name);
        if self.is_unlocked_for_write(&child_rel) {
            reply.error(EACCES);
            return;
        }
        let path = self.backing_path(&child_rel);
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        match OpenOptions::new().create(true).write(true).mode(mode).open(&path) {
            Ok(_) => match self.file_attr_for_rel(&child_rel) {
                Ok(attr) => reply.entry(&TTL, &attr, 0),
                Err(code) => reply.error(code),
            },
            Err(_) => reply.error(EACCES),
        }
    }

    fn mkdir(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, mode: u32, _umask: u32, reply: ReplyEntry) {
        debug_log(format!("mkdir parent={parent} name={} mode={mode:o}", name.to_string_lossy()));
        let Some(parent_rel) = self.rel_for_ino(parent) else {
            reply.error(ENOENT);
            return;
        };
        let child_rel = self.child_rel(&parent_rel, name);
        let path = self.backing_path(&child_rel);
        let mut builder = DirBuilder::new();
        builder.mode(mode);
        match builder.create(&path) {
            Ok(_) => match self.file_attr_for_rel(&child_rel) {
                Ok(attr) => reply.entry(&TTL, &attr, 0),
                Err(code) => reply.error(code),
            },
            Err(_) => reply.error(EACCES),
        }
    }

    fn setattr(&mut self, _req: &Request<'_>, ino: u64, _mode: Option<u32>, _uid: Option<u32>, _gid: Option<u32>, size: Option<u64>, _atime: Option<fuser::TimeOrNow>, _mtime: Option<fuser::TimeOrNow>, _ctime: Option<SystemTime>, _fh: Option<u64>, _crtime: Option<SystemTime>, _chgtime: Option<SystemTime>, _bkuptime: Option<SystemTime>, _flags: Option<u32>, reply: ReplyAttr) {
        debug_log(format!("setattr ino={ino} size={size:?}"));
        let Some(rel) = self.rel_for_ino(ino) else {
            reply.error(ENOENT);
            return;
        };
        if size.is_some() && self.is_unlocked_for_write(&rel) {
            reply.error(EACCES);
            return;
        }
        let path = self.backing_path(&rel);
        if let Some(next_size) = size {
            let file = match OpenOptions::new().write(true).open(&path) {
                Ok(file) => file,
                Err(_) => {
                    reply.error(ENOENT);
                    return;
                }
            };
            if file.set_len(next_size).is_err() {
                reply.error(EACCES);
                return;
            }
        }
        match self.file_attr_for_rel(&rel) {
            Ok(attr) => reply.attr(&TTL, &attr),
            Err(code) => reply.error(code),
        }
    }

    fn unlink(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, reply: ReplyEmpty) {
        debug_log(format!("unlink parent={parent} name={}", name.to_string_lossy()));
        let Some(parent_rel) = self.rel_for_ino(parent) else {
            reply.error(ENOENT);
            return;
        };
        let child_rel = self.child_rel(&parent_rel, name);
        if self.is_unlocked_for_write(&child_rel) {
            reply.error(EACCES);
            return;
        }
        match fs::remove_file(self.backing_path(&child_rel)) {
            Ok(_) => reply.ok(),
            Err(_) => reply.error(ENOENT),
        }
    }

    fn rmdir(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, reply: ReplyEmpty) {
        debug_log(format!("rmdir parent={parent} name={}", name.to_string_lossy()));
        let Some(parent_rel) = self.rel_for_ino(parent) else {
            reply.error(ENOENT);
            return;
        };
        let child_rel = self.child_rel(&parent_rel, name);
        match fs::remove_dir(self.backing_path(&child_rel)) {
            Ok(_) => reply.ok(),
            Err(_) => reply.error(ENOENT),
        }
    }

    fn rename(&mut self, _req: &Request<'_>, parent: u64, name: &OsStr, newparent: u64, newname: &OsStr, _flags: u32, reply: ReplyEmpty) {
        debug_log("rename");
        let Some(parent_rel) = self.rel_for_ino(parent) else {
            reply.error(ENOENT);
            return;
        };
        let Some(newparent_rel) = self.rel_for_ino(newparent) else {
            reply.error(ENOENT);
            return;
        };
        let old_rel = self.child_rel(&parent_rel, name);
        let new_rel = self.child_rel(&newparent_rel, newname);
        if self.is_locked_rel(&old_rel) || self.is_locked_rel(&new_rel) {
            reply.error(EPERM);
            return;
        }
        match fs::rename(self.backing_path(&old_rel), self.backing_path(&new_rel)) {
            Ok(_) => reply.ok(),
            Err(_) => reply.error(ENOENT),
        }
    }
}

fn prepare_mount_layout(fs_view: &GuardFs) -> std::io::Result<()> {
    let mount_dir = fs_view.workspace.mount_dir();
    ensure_root_lock_entry(fs_view)?;
    fs::create_dir_all(fs_view.managed_root())?;
    fs::create_dir_all(&mount_dir)?;
    sync_trees(&mount_dir, &fs_view.managed_root())
}

fn restore_public_layout(fs_view: &GuardFs) -> std::io::Result<()> {
    let mount_dir = fs_view.workspace.mount_dir();
    fs::create_dir_all(&mount_dir)?;
    clear_directory(&mount_dir)?;
    restore_tree(&fs_view.managed_root(), &mount_dir)
}

fn unmount(root: &Path) -> anyhow::Result<()> {
    let mount_dir = root.join(".agent");
    let fs_view = GuardFs::for_root(root.to_path_buf());
    for command in [["fusermount3", "-u"], ["fusermount", "-u"]] {
        if Command::new(command[0]).arg(command[1]).arg(&mount_dir).status().map(|s| s.success()).unwrap_or(false) {
            restore_public_layout(&fs_view)?;
            return Ok(());
        }
    }
    anyhow::bail!("failed to unmount {}", mount_dir.display())
}

fn mount(root: PathBuf) -> anyhow::Result<()> {
    let fs = GuardFs::for_root(root.clone());
    prepare_mount_layout(&fs)?;
    let options = mount_options();
    fuser::mount2(fs, root.join(".agent"), &options)?;
    Ok(())
}

fn mount_options() -> Vec<MountOption> {
    vec![
        MountOption::FSName("agent-guard-fuse".to_string()),
        MountOption::DefaultPermissions,
    ]
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Mount { root } => mount(root),
        Commands::Unmount { root } => unmount(&root),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    static FUSE_TEST_MUTEX: OnceLock<Mutex<()>> = OnceLock::new();

    fn test_lock() -> std::sync::MutexGuard<'static, ()> {
        FUSE_TEST_MUTEX
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn write_lock_file(home: &Path, root: &Path, token: &str, files: &[&str]) {
        let lock_dir = home.join(".agent-guard-fuse");
        fs::create_dir_all(&lock_dir).expect("create lock dir");
        let files_json = files
            .iter()
            .map(|item| format!("\"{item}\""))
            .collect::<Vec<_>>()
            .join(",");
        let payload = format!(
            "{{\"version\":3,\"roots\":{{\"{}\":{{\"managed\":\"{}\",\"token\":\"{}\",\"files\":[{}]}}}}}}",
            normalize_root_path(root),
            home.join(".agent-guard-fuse")
                .join("managed")
                .join(derive_state_id(root))
                .display(),
            token,
            files_json
        );
        fs::write(lock_dir.join("lock.json"), payload).expect("write lock file");
    }

    fn write_invalid_lock_file(home: &Path) {
        let lock_dir = home.join(".agent-guard-fuse");
        fs::create_dir_all(&lock_dir).expect("create lock dir");
        fs::write(lock_dir.join("lock.json"), "{not-json").expect("write invalid lock file");
    }

    fn setup_paths() -> (TempDir, TempDir, GuardFs) {
        let root = tempfile::tempdir().expect("create root tempdir");
        let home = tempfile::tempdir().expect("create home tempdir");
        let fs_view = GuardFs::new(root.path().to_path_buf(), home.path().to_path_buf());
        (root, home, fs_view)
    }

    #[test]
    fn derive_state_id_is_stable() {
        let _guard = test_lock();
        let temp = tempfile::tempdir().expect("create tempdir");
        assert_eq!(derive_state_id(temp.path()), derive_state_id(temp.path()));
    }

    #[test]
    fn load_locks_tolerates_missing_and_invalid_files() {
        let _guard = test_lock();
        let (_root, home, fs_view) = setup_paths();
        assert!(fs_view.load_locks().roots.is_empty());
        write_invalid_lock_file(home.path());
        assert!(fs_view.load_locks().roots.is_empty());
    }

    #[test]
    fn lock_presence_controls_write_authorization() {
        let _guard = test_lock();
        let (_root, home, fs_view) = setup_paths();
        assert!(!fs_view.is_unlocked_for_write(Path::new("state.json")));
        write_lock_file(home.path(), &fs_view.workspace.root, "token-1", &["state.json"]);
        assert!(fs_view.is_unlocked_for_write(Path::new("state.json")));
    }

    #[test]
    fn files_list_controls_authorization_only() {
        let _guard = test_lock();
        let (_root, home, mut fs_view) = setup_paths();
        let managed_plan = fs_view.managed_root().join("plan.yaml");
        fs::create_dir_all(managed_plan.parent().expect("managed parent"))
            .expect("create managed root");
        fs::write(&managed_plan, "steps: []\n").expect("write managed plan");
        let lock_dir = home.path().join(".agent-guard-fuse");
        fs::create_dir_all(&lock_dir).expect("create lock dir");
        let payload = format!(
            "{{\"version\":3,\"roots\":{{\"{}\":{{\"managed\":\"{}\",\"token\":\"token-1\",\"files\":[\"state.json\"]}}}}}}",
            fs_view.workspace.root_key(),
            home.path()
                .join(".agent-guard-fuse")
                .join("managed")
                .join(fs_view.workspace.state_id())
                .display()
        );
        fs::write(lock_dir.join("lock.json"), payload).expect("write lock file");

        assert!(fs_view.is_locked_rel(Path::new("state.json")));
        assert!(!fs_view.is_locked_rel(Path::new("plan.yaml")));
        assert!(fs_view.is_unlocked_for_write(Path::new("state.json")));
        assert!(!fs_view.is_unlocked_for_write(Path::new("plan.yaml")));
        assert!(fs_view.file_attr_for_rel(Path::new("plan.yaml")).is_ok());
    }

    #[test]
    fn root_entries_include_managed_directories() {
        let _guard = test_lock();
        let (_root, _home, fs_view) = setup_paths();
        let artifacts = fs_view.managed_root().join("artifacts");
        fs::create_dir_all(&artifacts).expect("create artifacts dir");
        fs::write(fs_view.managed_root().join("jobs.json"), "{\"jobs\":[]}\n").expect("write jobs");
        let names = fs_view.visible_root_entries();

        assert!(names.contains(&"artifacts".to_string()));
        assert!(names.contains(&"jobs.json".to_string()));
    }

    #[test]
    fn prepare_mount_layout_moves_public_content_into_managed_state() {
        let _guard = test_lock();
        let (_root, _home, fs_view) = setup_paths();
        let public = fs_view.public_path("state.json");
        fs::create_dir_all(public.parent().expect("public parent")).expect("create .agent");
        fs::write(&public, "{\"stage\":\"IDLE\"}\n").expect("write public file");

        prepare_mount_layout(&fs_view).expect("prepare mount layout");

        assert_eq!(
            fs::read_to_string(fs_view.managed_root().join("state.json")).expect("read managed state"),
            "{\"stage\":\"IDLE\"}\n"
        );
        assert_eq!(fs::read_to_string(&public).expect("read synced public state"), "{\"stage\":\"IDLE\"}\n");
    }

    #[test]
    fn prepare_mount_layout_preserves_existing_managed_state() {
        let _guard = test_lock();
        let (_root, _home, fs_view) = setup_paths();
        let managed = fs_view.managed_root().join("plan.yaml");
        fs::create_dir_all(managed.parent().expect("managed parent")).expect("create managed dir");
        fs::write(&managed, "steps: []\n").expect("write managed file");

        let public = fs_view.public_path("plan.yaml");
        fs::create_dir_all(public.parent().expect("public parent")).expect("create .agent");
        fs::write(&public, "stale: true\n").expect("write stale public file");

        prepare_mount_layout(&fs_view).expect("prepare mount layout");

        assert_eq!(fs::read_to_string(&managed).expect("read managed plan"), "steps: []\n");
        assert_eq!(fs::read_to_string(&public).expect("read synced public plan"), "steps: []\n");
    }

    #[test]
    fn prepare_mount_layout_syncs_passthrough_content_into_managed_root() {
        let _guard = test_lock();
        let (_root, _home, fs_view) = setup_paths();
        let events = fs_view.public_path("events.jsonl");
        let artifacts = fs_view.public_path("artifacts");
        fs::create_dir_all(&artifacts).expect("create artifacts");
        fs::write(&events, "{\"event\":\"ok\"}\n").expect("write events");

        prepare_mount_layout(&fs_view).expect("prepare mount layout");

        assert_eq!(
            fs::read_to_string(fs_view.managed_root().join("events.jsonl")).expect("read passthrough file"),
            "{\"event\":\"ok\"}\n"
        );
        assert!(fs_view.managed_root().join("artifacts").is_dir());
    }

}
