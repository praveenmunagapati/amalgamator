"""
Build cache — enables incremental builds by hashing source files.

Stores file hashes and dependency graphs to skip re-amalgamation
when nothing has changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


CACHE_DIR = ".amalgamator_cache"
CACHE_FILE = "build_cache.json"


class BuildCache:
    """
    Tracks file hashes to detect changes and enable incremental builds.

    Cache is stored in .amalgamator_cache/build_cache.json.
    """

    def __init__(self, project_dir: Path) -> None:
        self.cache_dir = project_dir / CACHE_DIR
        self.cache_file = self.cache_dir / CACHE_FILE
        self._data: dict = self._load()

    def _load(self) -> dict:
        """Load cache from disk."""
        if not self.cache_file.exists():
            return {"version": 1, "files": {}, "output_hash": ""}

        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "files": {}, "output_hash": ""}

    def save(self) -> None:
        """Write cache to disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(self._data, indent=2),
            encoding="utf-8",
        )

    def has_changed(self, files: list[Path]) -> bool:
        """
        Check if any source files have changed since the last build.

        Returns True if a rebuild is needed, False if cache is valid.
        """
        current_hashes = self._compute_hashes(files)
        cached_hashes = self._data.get("files", {})

        # Different number of files = changed
        if set(current_hashes.keys()) != set(cached_hashes.keys()):
            return True

        # Any hash mismatch = changed
        for file_key, file_hash in current_hashes.items():
            if cached_hashes.get(file_key) != file_hash:
                return True

        return False

    def update(self, files: list[Path], output_path: Path | None = None) -> None:
        """Update the cache with current file hashes."""
        self._data["files"] = self._compute_hashes(files)

        if output_path and output_path.exists():
            self._data["output_hash"] = _file_hash(output_path)

        self.save()

    def get_output_hash(self) -> str:
        """Get the hash of the last amalgamated output."""
        return self._data.get("output_hash", "")

    def invalidate(self) -> None:
        """Clear the cache."""
        self._data = {"version": 1, "files": {}, "output_hash": ""}
        if self.cache_file.exists():
            self.cache_file.unlink()

    @staticmethod
    def _compute_hashes(files: list[Path]) -> dict[str, str]:
        """Compute SHA-256 hashes for all files."""
        hashes: dict[str, str] = {}
        for f in files:
            if f.exists():
                hashes[str(f)] = _file_hash(f)
        return hashes


def _file_hash(path: Path, block_size: int = 65536) -> str:
    """Compute the SHA-256 hash of a file."""
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                block = f.read(block_size)
                if not block:
                    break
                sha.update(block)
    except OSError:
        return ""
    return sha.hexdigest()
