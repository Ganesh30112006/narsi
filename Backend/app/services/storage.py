"""Storage abstraction. The application depends on `StorageBackend`, never on the filesystem directly,
so an S3/MinIO backend can be added without touching services.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageBackend(Protocol):
    def save(self, source: Path, *, namespace: str, extension: str) -> tuple[str, str]:
        """Stores `source`; returns (reference, safe_filename)."""
        ...

    def open(self, reference: str) -> BinaryIO: ...

    @contextmanager
    def local_path(self, reference: str) -> Iterator[Path]:
        """A local filesystem path for libraries that need one (a temp copy for remote backends)."""
        ...

    def delete(self, reference: str) -> None: ...

    def exists(self, reference: str) -> bool: ...


class LocalStorage:
    """Stores files under a root directory with generated names, outside any web-served directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, reference: str) -> Path:
        path = (self.root / reference).resolve()
        if not path.is_relative_to(self.root):  # path-traversal guard
            raise ValueError("Invalid storage reference")
        return path

    def save(self, source: Path, *, namespace: str, extension: str) -> tuple[str, str]:
        safe_name = f"{uuid.uuid4().hex}.{extension}"
        reference = f"{namespace}/{safe_name[:2]}/{safe_name}"
        destination = self._resolve(reference)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        with contextlib.suppress(OSError):  # not supported on every platform
            os.chmod(destination, 0o600)
        return reference, safe_name

    def open(self, reference: str) -> BinaryIO:
        return self._resolve(reference).open("rb")

    @contextmanager
    def local_path(self, reference: str) -> Iterator[Path]:
        yield self._resolve(reference)

    def delete(self, reference: str) -> None:
        self._resolve(reference).unlink(missing_ok=True)

    def exists(self, reference: str) -> bool:
        return self._resolve(reference).is_file()


_storage: StorageBackend | None = None


def get_storage(settings: Settings) -> StorageBackend:
    global _storage
    if _storage is None:
        _storage = LocalStorage(settings.upload_directory)
    return _storage


def set_storage(storage: StorageBackend | None) -> None:
    """Test hook."""
    global _storage
    _storage = storage


@contextmanager
def temp_workspace(settings: Settings, prefix: str = "work-") -> Iterator[Path]:
    """A private temporary directory that is always removed, whether processing succeeds or fails."""
    settings.temp_directory.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=settings.temp_directory))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def cleanup_stale_workspaces(settings: Settings, *, max_age_seconds: int = 3600) -> int:
    """Removes temp directories left behind by crashed processes. Returns how many were removed."""
    if not settings.temp_directory.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for entry in settings.temp_directory.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True) if entry.is_dir() else entry.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("temp_cleanup", extra={"removed": removed})
    return removed
