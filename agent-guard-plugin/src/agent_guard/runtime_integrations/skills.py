"""Shared workflow-skill discovery, selection, and installation."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..workflow_spec import install_defaults as workflow_install_defaults


def shared_skills_install_dir(scope: str, cwd: Path, home_dir: Path) -> Path:
    """Return the legacy shared skill directory used by older Codex installs."""
    return cwd / ".agent-guard" / "skills" if scope == "project" else home_dir / ".agent-guard" / "skills"


def packaged_skills_dir() -> Path:
    """Locate workflow skills in an installed wheel or source checkout."""
    package_dir = Path(__file__).resolve().parent.parent
    bundled_dir = package_dir / "_bundled_skills"
    if bundled_dir.exists() and any(bundled_dir.glob("*.md")):
        return bundled_dir

    repo_root = package_dir.parents[1]
    docs_dir = repo_root / "docs" / "skills"
    if docs_dir.exists() and any(docs_dir.glob("*.md")):
        return docs_dir

    return bundled_dir


def source_skills_dir(plugin_root: Path) -> Path:
    """Resolve the source-of-truth skill directory for an installation."""
    candidates = [plugin_root / "docs" / "skills", packaged_skills_dir()]
    for candidate in candidates:
        if candidate.exists() and any(candidate.glob("*.md")):
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise RuntimeError(f"Could not locate bundled workflow skills. Searched: {searched}")


def skill_slug_from_source(source_file: Path) -> str:
    """Return the native skill directory name for a Markdown source."""
    return source_file.stem


def _skill_match_haystack(source_file: Path) -> str:
    return "\n".join([skill_slug_from_source(source_file), source_file.name])


def _compile_matchers(patterns: list[str], label: str) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error as exc:
            raise RuntimeError(f"Invalid {label} regex {pattern!r}: {exc}") from exc
    return compiled


def selected_skill_sources(
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
) -> list[Path]:
    """Select skill sources using positive and negative regex filters."""
    source_files = sorted(source_skills_dir(plugin_root).glob("*.md"))
    include_patterns = _compile_matchers(include_matches or [], "--match")
    exclude_patterns = _compile_matchers(exclude_matches or [], "--exclude-match")

    selected: list[Path] = []
    for source_file in source_files:
        haystack = _skill_match_haystack(source_file)
        if include_patterns and not any(pattern.search(haystack) for pattern in include_patterns):
            continue
        if exclude_patterns and any(pattern.search(haystack) for pattern in exclude_patterns):
            continue
        selected.append(source_file)
    return selected


def resolve_skill_filters(
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    *,
    root_dir: Path | None = None,
    workflow_id: str | None = None,
) -> tuple[list[str], list[str], str]:
    """Resolve filters from explicit CLI values or workflow defaults."""
    cli_include = list(include_matches or [])
    cli_exclude = list(exclude_matches or [])
    if cli_include or cli_exclude:
        return cli_include, cli_exclude, "cli"

    defaults = workflow_install_defaults(root_dir, workflow_id)
    return list(defaults.get("skill_match", [])), list(defaults.get("skill_exclude_match", [])), "workflow"


def install_selection_warning(source: str, include_matches: list[str], exclude_matches: list[str]) -> str:
    """Explain why workflow-default filters were ignored."""
    details: list[str] = []
    if include_matches:
        details.append(f"match={include_matches!r}")
    if exclude_matches:
        details.append(f"exclude_match={exclude_matches!r}")
    rendered = ", ".join(details) if details else "no filters"
    return (
        "Workflow skill selection matched no installable skills; "
        f"ignoring {rendered} from {source} defaults and falling back to full install."
    )


def selected_skill_sources_with_fallback(
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    *,
    root_dir: Path | None = None,
    workflow_id: str | None = None,
) -> tuple[list[Path], list[str]]:
    """Select skills and fall back when only workflow defaults match nothing."""
    resolved_include, resolved_exclude, source = resolve_skill_filters(
        include_matches,
        exclude_matches,
        root_dir=root_dir,
        workflow_id=workflow_id,
    )
    selected = selected_skill_sources(plugin_root, resolved_include, resolved_exclude)
    if selected or source != "workflow" or (not resolved_include and not resolved_exclude):
        return selected, []
    return sorted(source_skills_dir(plugin_root).glob("*.md")), [
        install_selection_warning(source, resolved_include, resolved_exclude)
    ]


def install_flat_skills_bundle(
    target_dir: Path,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    *,
    root_dir: Path | None = None,
    workflow_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """Install selected skills using the legacy flat Markdown layout."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    selected_sources, warnings = selected_skill_sources_with_fallback(
        plugin_root,
        include_matches,
        exclude_matches,
        root_dir=root_dir,
        workflow_id=workflow_id,
    )
    for source_file in selected_sources:
        target_file = target_dir / source_file.name
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError("No workflow skills were installed.")
    return written_files, warnings


def install_native_skills_bundle(
    target_dir: Path,
    plugin_root: Path,
    include_matches: list[str] | None = None,
    exclude_matches: list[str] | None = None,
    *,
    empty_error: str,
    root_dir: Path | None = None,
    workflow_id: str | None = None,
) -> tuple[list[str], list[str]]:
    """Install selected skills in native ``<skill>/SKILL.md`` layout."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written_files: list[str] = []
    selected_sources, warnings = selected_skill_sources_with_fallback(
        plugin_root,
        include_matches,
        exclude_matches,
        root_dir=root_dir,
        workflow_id=workflow_id,
    )
    for source_file in selected_sources:
        legacy_target = target_dir / source_file.name
        if legacy_target.exists():
            legacy_target.unlink()
        target_file = target_dir / skill_slug_from_source(source_file) / "SKILL.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
        written_files.append(str(target_file))
    if not written_files:
        raise RuntimeError(empty_error)
    return written_files, warnings


def remove_legacy_skill_copies(skills_root: Path, reserved_dir: Path, source_root: Path) -> None:
    """Remove old flat and standalone native copies managed by agent-guard."""
    if not skills_root.exists():
        return
    for source_file in sorted(source_skills_dir(source_root).glob("*.md")):
        skill_id = skill_slug_from_source(source_file)
        legacy_flat = skills_root / f"{skill_id}.md"
        if legacy_flat.exists():
            legacy_flat.unlink()
        legacy_native = skills_root / skill_id
        if legacy_native == reserved_dir:
            continue
        legacy_skill = legacy_native / "SKILL.md"
        if legacy_skill.exists():
            shutil.rmtree(legacy_native)
