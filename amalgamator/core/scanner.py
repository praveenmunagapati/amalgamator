"""
File scanner — discovers and filters source files in a directory.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from amalgamator.utils.detection import (
    EXTENSION_MAP,
    SOURCE_LANGUAGES,
    DATA_FORMATS,
    get_source_extensions,
)

DEFAULT_EXCLUDES: list[str] = [
    ".git", ".svn", ".hg",
    "build", "dist", "out", "target", "bin", "obj",
    "node_modules", "__pycache__", ".tox", ".venv", "venv", "env", ".env",
    ".vscode", ".idea", ".vs", "*.swp", "*.swo", "*~",
    ".DS_Store", "Thumbs.db",
    "amalgamated*", "amalgamated.*",  # Exclude previously generated outputs
]


class FileSet:
    """A collection of discovered files with metadata."""

    def __init__(self, files: list[Path], base_path: Path, language: str | None = None) -> None:
        self.files = files
        self.base_path = base_path
        self.language = language

    def __len__(self) -> int:
        return len(self.files)

    def __iter__(self):
        return iter(self.files)

    @property
    def total_size(self) -> int:
        return sum(f.stat().st_size for f in self.files if f.exists())

    def relative_paths(self) -> list[Path]:
        result = []
        for f in self.files:
            try:
                result.append(f.relative_to(self.base_path))
            except ValueError:
                result.append(f)
        return result


def scan_directory(
    path: Path,
    language: str | None = None,
    extensions: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    include_data: bool = False,
    recursive: bool = True,
) -> FileSet:
    """Scan a directory for source files."""
    path = path.resolve()

    if path.is_file():
        return FileSet(files=[path], base_path=path.parent, language=language)

    if not path.is_dir():
        raise FileNotFoundError(f"Path does not exist: {path}")

    allowed_extensions = _build_extension_set(language, extensions, include_data)

    excludes = list(DEFAULT_EXCLUDES)
    if exclude_patterns:
        excludes.extend(exclude_patterns)
    excludes.extend(_load_gitignore(path))

    files: list[Path] = []
    iterator = path.rglob("*") if recursive else path.glob("*")

    for file_path in iterator:
        if not file_path.is_file():
            continue
        if _is_excluded(file_path, path, excludes):
            continue
        if allowed_extensions and file_path.suffix.lower() not in allowed_extensions:
            continue
        files.append(file_path)

    files.sort()
    return FileSet(files=files, base_path=path, language=language)


def scan_files(file_paths: list[Path], language: str | None = None) -> FileSet:
    """Create a FileSet from an explicit list of file paths."""
    resolved = [Path(fp).resolve() for fp in file_paths if Path(fp).resolve().is_file()]
    if not resolved:
        raise FileNotFoundError("No valid files found in the provided list.")

    base = resolved[0].parent if len(resolved) == 1 else _common_parent(resolved)
    return FileSet(files=sorted(resolved), base_path=base, language=language)


def _build_extension_set(language, extensions, include_data) -> set[str]:
    if extensions:
        return {ext if ext.startswith(".") else f".{ext}" for ext in extensions}
    if language:
        return set(get_source_extensions(language))
    allowed = set()
    for ext, lang in EXTENSION_MAP.items():
        if lang in SOURCE_LANGUAGES:
            allowed.add(ext)
        elif include_data and lang in DATA_FORMATS:
            allowed.add(ext)
    return allowed


def _is_excluded(file_path: Path, base_path: Path, patterns: list[str]) -> bool:
    try:
        relative = file_path.relative_to(base_path)
    except ValueError:
        relative = file_path
    relative_str = str(relative).replace("\\", "/")
    parts = relative.parts
    for pattern in patterns:
        if fnmatch.fnmatch(file_path.name, pattern):
            return True
        if fnmatch.fnmatch(relative_str, pattern):
            return True
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _load_gitignore(directory: Path) -> list[str]:
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        return []
    patterns = []
    try:
        for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("!"):
                patterns.append(line.lstrip("/"))
    except OSError:
        pass
    return patterns


def _common_parent(paths: list[Path]) -> Path:
    if not paths:
        return Path(".")
    parts_list = [p.parts for p in paths]
    common = []
    for components in zip(*parts_list):
        if len(set(components)) == 1:
            common.append(components[0])
        else:
            break
    return Path(*common) if common else paths[0].parent
