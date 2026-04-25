"""Storage helpers for AISO scan artifacts.

The current zero-infra setup keeps generated files on disk. These helpers keep
paths deterministic and make artifact metadata portable to object storage later.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE_ROOT = "storage"
_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_storage_part(value: str) -> str:
    """Return a path-safe identifier segment."""
    clean = _SAFE_PART_RE.sub("-", str(value or "").strip()).strip(".-")
    if not clean:
        raise ValueError("storage path segment cannot be empty")
    return clean[:120]


def local_storage_root() -> Path:
    """Resolve the local storage root from AISO_STORAGE_ROOT."""
    configured = Path(os.getenv("AISO_STORAGE_ROOT", DEFAULT_STORAGE_ROOT))
    if configured.is_absolute():
        return configured
    return REPO_ROOT / configured


def build_scan_artifact_path(
    client_id: str,
    scan_id: str,
    filename: str,
    *,
    stage: str = "raw",
) -> Path:
    """Build a deterministic local path for a scan artifact."""
    return (
        local_storage_root()
        / "clients"
        / safe_storage_part(client_id)
        / "scans"
        / safe_storage_part(scan_id)
        / safe_storage_part(stage)
        / safe_storage_part(filename)
    )


def repo_relative_path(path: str | Path) -> str:
    """Return a stable repo-relative path when possible."""
    resolved = Path(path).expanduser().resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def file_sha256(path: str | Path) -> str:
    """Calculate a SHA-256 digest for a local file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_local_artifact(
    path: str | Path,
    *,
    artifact_type: str,
    original_filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build DB-ready metadata for a local artifact path."""
    local_path = Path(path).expanduser()
    suffix = local_path.suffix.lower().lstrip(".")
    exists = local_path.exists() and local_path.is_file()

    return {
        "artifact_type": artifact_type,
        "file_format": suffix or None,
        "storage_backend": "local",
        "storage_path": repo_relative_path(local_path),
        "original_filename": original_filename or local_path.name,
        "mime_type": mimetypes.guess_type(local_path.name)[0],
        "size_bytes": local_path.stat().st_size if exists else None,
        "sha256": file_sha256(local_path) if exists else None,
        "metadata_json": json.dumps(metadata or {}, sort_keys=True),
    }
