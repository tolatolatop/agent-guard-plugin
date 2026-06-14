"""Helpers for treating artifact paths as files, directories, or glob patterns."""
from __future__ import annotations

from pathlib import Path

from .managed_documents import managed_document_backing_path, managed_document_kind_for_path

_GLOB_CHARS = "*?["


def _normalize_artifact_path(artifact_path: str) -> str:
    return artifact_path.replace("\\", "/").removeprefix("./")


def _is_glob_pattern(artifact_path: str) -> bool:
    return any(char in artifact_path for char in _GLOB_CHARS)


def _expand_candidate(candidate: Path) -> list[Path]:
    if not candidate.exists():
        return []
    if candidate.is_dir():
        expanded = [candidate]
        expanded.extend(path for path in candidate.rglob("*"))
        return expanded
    return [candidate]


def resolve_artifact_pattern(root_dir: Path, artifact_path: str) -> list[Path]:
    """Resolve one artifact path as an exact file, directory, or glob pattern."""
    normalized = _normalize_artifact_path(artifact_path)
    if not _is_glob_pattern(normalized):
        if managed_document_kind_for_path(normalized) is not None:
            candidate = managed_document_backing_path(root_dir, normalized)
        else:
            candidate = root_dir / normalized
        resolved = _expand_candidate(candidate)
    else:
        resolved = []
        for candidate in root_dir.glob(normalized):
            resolved.extend(_expand_candidate(candidate))
    deduped: dict[str, Path] = {}
    for path in resolved:
        deduped[str(path)] = path
    return [deduped[key] for key in sorted(deduped)]


def _safe_mtime_ns(path: Path) -> int | None:
    """Return a path mtime, skipping broken symlinks or vanished files."""
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return None


def artifact_pattern_mtime_ns(root_dir: Path, artifact_path: str) -> int | None:
    """Return the latest mtime across all concrete paths resolved from one artifact pattern."""
    mtimes = [mtime for _, mtime in artifact_pattern_mtime_candidates(root_dir, artifact_path)]
    if not mtimes:
        return None
    return max(mtimes)


def artifact_pattern_mtime_candidates(root_dir: Path, artifact_path: str) -> list[tuple[Path, int]]:
    """Return resolved artifact candidates paired with their mtimes."""
    resolved = resolve_artifact_pattern(root_dir, artifact_path)
    candidates: list[tuple[Path, int]] = []
    for path in resolved:
        mtime = _safe_mtime_ns(path)
        if mtime is not None:
            candidates.append((path, mtime))
    return candidates


def artifact_pattern_text_candidates(root_dir: Path, artifact_path: str) -> list[Path]:
    """Return regular files resolved from one artifact pattern, for content validation."""
    return [path for path in resolve_artifact_pattern(root_dir, artifact_path) if path.is_file()]
