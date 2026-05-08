"""Storage helpers for AISO scan artifacts.

The current zero-infra setup keeps generated files on disk. These helpers keep
paths deterministic and make artifact metadata portable to object storage later.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE_ROOT = "storage"
_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9._-]+")
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_BASE_URL = "https://login.microsoftonline.com"
ONEDRIVE_SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024
ONEDRIVE_CHUNK_SIZE = 5 * 1024 * 1024


class ArtifactStorageError(RuntimeError):
    """Safe artifact storage error that never includes secrets."""


@dataclass(frozen=True)
class OneDriveUploadResult:
    drive_id: str
    item_id: str
    remote_path: str
    web_url: str | None


def safe_storage_part(value: str) -> str:
    """Return a path-safe identifier segment."""
    clean = _SAFE_PART_RE.sub("-", str(value or "").strip()).strip(".-")
    if not clean:
        raise ValueError("storage path segment cannot be empty")
    return clean[:120]


def configured_storage_backend() -> str:
    """Return the artifact storage backend configured for this process."""
    backend = os.getenv("AISO_STORAGE_BACKEND", "local").strip().lower()
    if backend in {"", "local"}:
        return "local"
    if backend == "onedrive":
        return "onedrive"
    raise ArtifactStorageError(f"Unsupported artifact storage backend: {backend}")


def client_artifact_slug(client_name: str, client_id: str) -> str:
    """Build a stable, readable, collision-resistant client artifact slug."""
    readable = safe_storage_part(str(client_name or "client").lower())
    suffix = safe_storage_part(str(client_id or "client")[:8].lower())
    return f"{readable}--{suffix}"


def onedrive_remote_dir(client_name: str, client_id: str, scan_id: str) -> str:
    """Return the OneDrive folder for a scan's artifacts."""
    base = os.getenv("AISO_ONEDRIVE_BASE_PATH", "/AISO").strip() or "/AISO"
    clean_base = "/" + "/".join(
        safe_storage_part(part)
        for part in base.strip("/").split("/")
        if part.strip()
    )
    return (
        f"{clean_base}/clients/"
        f"{client_artifact_slug(client_name, client_id)}/scans/"
        f"{safe_storage_part(scan_id)}"
    )


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


def _metadata_json(metadata: dict[str, Any] | None) -> str:
    return json.dumps(metadata or {}, sort_keys=True)


def _base_local_artifact_metadata(
    path: str | Path,
    *,
    artifact_type: str,
    original_filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        "metadata_json": _metadata_json(metadata),
    }


def describe_local_artifact(
    path: str | Path,
    *,
    artifact_type: str,
    original_filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build DB-ready metadata for a local artifact path."""
    return _base_local_artifact_metadata(
        path,
        artifact_type=artifact_type,
        original_filename=original_filename,
        metadata=metadata,
    )


def describe_configured_artifact(
    path: str | Path,
    *,
    artifact_type: str,
    client_name: str,
    client_id: str,
    scan_id: str,
    original_filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build DB-ready artifact metadata for the configured storage backend.

    If remote upload fails, keep local artifact metadata and record a safe
    upload failure in metadata. Scan metrics should not be lost because storage
    had a transient issue.
    """
    base_metadata = dict(metadata or {})
    local_metadata = _base_local_artifact_metadata(
        path,
        artifact_type=artifact_type,
        original_filename=original_filename,
        metadata=base_metadata,
    )
    backend = configured_storage_backend()
    if backend == "local":
        return local_metadata

    if backend != "onedrive":
        return local_metadata

    remote_filename = original_filename or Path(path).name
    remote_dir = onedrive_remote_dir(client_name, client_id, scan_id)
    remote_path = f"{remote_dir}/{safe_storage_part(remote_filename)}"
    try:
        upload = upload_file_to_onedrive(Path(path), remote_path)
    except (ArtifactStorageError, requests.RequestException) as exc:
        failed_metadata = {
            **base_metadata,
            "upload_backend": "onedrive",
            "upload_status": "failed",
            "upload_error": _safe_storage_exception_message(exc),
            "remote_path": remote_path,
        }
        local_metadata["metadata_json"] = _metadata_json(failed_metadata)
        return local_metadata

    uploaded_metadata = {
        **base_metadata,
        "upload_backend": "onedrive",
        "upload_status": "uploaded",
        "remote_path": upload.remote_path,
        "onedrive_drive_id": upload.drive_id,
        "onedrive_item_id": upload.item_id,
    }
    if upload.web_url:
        uploaded_metadata["onedrive_web_url_present"] = True

    local_metadata.update(
        {
            "storage_backend": "onedrive",
            "storage_path": f"onedrive://{upload.drive_id}/{upload.item_id}",
            "metadata_json": _metadata_json(uploaded_metadata),
        }
    )
    return local_metadata


def resolve_local_artifact_path(storage_path: str) -> Path:
    """Resolve a local artifact path while keeping it inside allowed roots."""
    raw_path = Path(storage_path).expanduser()
    candidate = raw_path if raw_path.is_absolute() else REPO_ROOT / raw_path
    resolved = candidate.resolve()
    allowed_roots = [
        local_storage_root().resolve(),
        (REPO_ROOT / "clients").resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ArtifactStorageError("Artifact path is not available")
    if not resolved.is_file():
        raise ArtifactStorageError("Artifact file not found")
    return resolved


@contextmanager
def materialize_artifact_file(artifact: Any):
    """Yield a local path for either a local or OneDrive artifact."""
    if artifact.storage_backend == "local":
        yield resolve_local_artifact_path(artifact.storage_path)
        return

    if artifact.storage_backend != "onedrive":
        raise ArtifactStorageError("Artifact storage backend is not supported")

    content = download_onedrive_artifact(artifact.storage_path)
    suffix = f".{artifact.file_format}" if getattr(artifact, "file_format", None) else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        temp_path = Path(handle.name)
        handle.write(content)
    try:
        yield temp_path
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _onedrive_tenant() -> str:
    return os.getenv("MICROSOFT_TENANT", "consumers").strip() or "consumers"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ArtifactStorageError(f"Missing required OneDrive setting: {name}")
    return value


def _graph_headers(access_token: str, *, content_type: str | None = "application/json") -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _safe_graph_error(response: requests.Response, fallback: str) -> ArtifactStorageError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else {}
    message = ""
    if isinstance(error, dict):
        message = str(error.get("message") or error.get("code") or "").strip()
    if not message:
        message = fallback
    return ArtifactStorageError(message[:300])


def _safe_storage_exception_message(exc: Exception) -> str:
    if isinstance(exc, ArtifactStorageError):
        return str(exc)[:300]
    if isinstance(exc, requests.RequestException):
        return "OneDrive network request failed"
    return "OneDrive artifact upload failed"


def _refresh_onedrive_access_token() -> str:
    response = requests.post(
        f"{TOKEN_BASE_URL}/{_onedrive_tenant()}/oauth2/v2.0/token",
        data={
            "client_id": _required_env("MICROSOFT_CLIENT_ID"),
            "client_secret": _required_env("MICROSOFT_CLIENT_SECRET"),
            "refresh_token": _required_env("MICROSOFT_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
            "scope": "offline_access Files.ReadWrite User.Read",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise _safe_graph_error(response, "Unable to refresh OneDrive access token")
    token = str(response.json().get("access_token") or "").strip()
    if not token:
        raise ArtifactStorageError("OneDrive token response did not include an access token")
    return token


def _graph_path(path: str) -> str:
    clean = "/" + "/".join(part for part in str(path or "").strip("/").split("/") if part)
    return quote(clean, safe="/._-()")


def _graph_get(access_token: str, endpoint: str) -> requests.Response:
    return requests.get(
        f"{GRAPH_BASE_URL}{endpoint}",
        headers=_graph_headers(access_token, content_type=None),
        timeout=20,
    )


def _ensure_onedrive_folder(access_token: str, folder_path: str) -> None:
    current = ""
    for part in [p for p in folder_path.strip("/").split("/") if p]:
        next_path = f"{current}/{part}" if current else f"/{part}"
        existing = _graph_get(access_token, f"/me/drive/root:{_graph_path(next_path)}")
        if existing.status_code == 200:
            current = next_path
            continue
        if existing.status_code != 404:
            raise _safe_graph_error(existing, "Unable to inspect OneDrive folder")

        if current:
            endpoint = f"/me/drive/root:{_graph_path(current)}:/children"
        else:
            endpoint = "/me/drive/root/children"
        created = requests.post(
            f"{GRAPH_BASE_URL}{endpoint}",
            headers=_graph_headers(access_token),
            json={
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            },
            timeout=20,
        )
        if created.status_code == 409:
            current = next_path
            continue
        if created.status_code >= 400:
            raise _safe_graph_error(created, "Unable to create OneDrive folder")
        current = next_path


def _drive_item_from_response(response: requests.Response, remote_path: str) -> OneDriveUploadResult:
    if response.status_code >= 400:
        raise _safe_graph_error(response, "Unable to upload OneDrive artifact")
    payload = response.json()
    parent = payload.get("parentReference") if isinstance(payload, dict) else {}
    drive_id = str((parent or {}).get("driveId") or "").strip()
    item_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
    if not drive_id or not item_id:
        raise ArtifactStorageError("OneDrive upload response was missing file identifiers")
    web_url = str(payload.get("webUrl") or "").strip() if isinstance(payload, dict) else ""
    return OneDriveUploadResult(
        drive_id=drive_id,
        item_id=item_id,
        remote_path=remote_path,
        web_url=web_url or None,
    )


def upload_file_to_onedrive(local_path: Path, remote_path: str) -> OneDriveUploadResult:
    """Upload a local file to OneDrive and return addressable metadata."""
    if not local_path.exists() or not local_path.is_file():
        raise ArtifactStorageError("Local artifact file does not exist")

    access_token = _refresh_onedrive_access_token()
    remote_dir = str(Path(remote_path).parent).replace("\\", "/")
    if remote_dir and remote_dir != ".":
        _ensure_onedrive_folder(access_token, remote_dir)

    if local_path.stat().st_size <= ONEDRIVE_SIMPLE_UPLOAD_LIMIT:
        with local_path.open("rb") as handle:
            response = requests.put(
                f"{GRAPH_BASE_URL}/me/drive/root:{_graph_path(remote_path)}:/content",
                headers=_graph_headers(access_token, content_type=mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"),
                data=handle,
                timeout=60,
            )
        return _drive_item_from_response(response, remote_path)

    session_response = requests.post(
        f"{GRAPH_BASE_URL}/me/drive/root:{_graph_path(remote_path)}:/createUploadSession",
        headers=_graph_headers(access_token),
        json={"item": {"@microsoft.graph.conflictBehavior": "replace"}},
        timeout=30,
    )
    if session_response.status_code >= 400:
        raise _safe_graph_error(session_response, "Unable to create OneDrive upload session")
    upload_url = str(session_response.json().get("uploadUrl") or "").strip()
    if not upload_url:
        raise ArtifactStorageError("OneDrive upload session did not include an upload URL")

    size = local_path.stat().st_size
    response: requests.Response | None = None
    with local_path.open("rb") as handle:
        start = 0
        while start < size:
            chunk = handle.read(ONEDRIVE_CHUNK_SIZE)
            end = start + len(chunk) - 1
            response = requests.put(
                upload_url,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                data=chunk,
                timeout=120,
            )
            if response.status_code not in {200, 201, 202}:
                raise _safe_graph_error(response, "Unable to upload OneDrive file chunk")
            start = end + 1

    if response is None:
        raise ArtifactStorageError("OneDrive upload did not send any bytes")
    return _drive_item_from_response(response, remote_path)


def _parse_onedrive_storage_path(storage_path: str) -> tuple[str, str]:
    if not storage_path.startswith("onedrive://"):
        raise ArtifactStorageError("Invalid OneDrive storage path")
    payload = storage_path.removeprefix("onedrive://")
    parts = payload.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ArtifactStorageError("Invalid OneDrive storage path")
    return parts[0], parts[1]


def download_onedrive_artifact(storage_path: str) -> bytes:
    """Download a OneDrive artifact by its stored drive/item address."""
    drive_id, item_id = _parse_onedrive_storage_path(storage_path)
    access_token = _refresh_onedrive_access_token()
    response = requests.get(
        f"{GRAPH_BASE_URL}/drives/{quote(drive_id)}/items/{quote(item_id)}/content",
        headers=_graph_headers(access_token, content_type=None),
        timeout=120,
    )
    if response.status_code >= 400:
        raise _safe_graph_error(response, "Unable to download OneDrive artifact")
    return response.content
