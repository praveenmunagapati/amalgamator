"""
Language and data format auto-detection.

Detects programming languages from file extensions, shebang lines, and content
heuristics. Also detects available compilers and runtimes on the system.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# ── Extension → language mapping ─────────────────────────────────────────────

EXTENSION_MAP: dict[str, str] = {
    # C / C++
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    # JavaScript / TypeScript
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    # Java
    ".java": "java",
    # Rust
    ".rs": "rust",
    # Go
    ".go": "go",
    # Data formats
    ".json": "json",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}

# ── Shebang → language mapping ───────────────────────────────────────────────

SHEBANG_MAP: dict[str, str] = {
    "python": "python",
    "python3": "python",
    "node": "javascript",
    "deno": "typescript",
    "ruby": "ruby",
    "perl": "perl",
    "bash": "bash",
    "sh": "bash",
}

# ── Language categories ──────────────────────────────────────────────────────

SOURCE_LANGUAGES = {"c", "cpp", "python", "javascript", "typescript", "java", "rust", "go"}
DATA_FORMATS = {"json", "xml", "yaml", "toml"}

# ── Compiler detection ───────────────────────────────────────────────────────

COMPILER_MAP: dict[str, list[str]] = {
    "c": ["gcc", "cc", "clang", "cl"],
    "cpp": ["g++", "c++", "clang++", "cl"],
    "java": ["javac"],
    "rust": ["rustc"],
    "go": ["go"],
}

RUNTIME_MAP: dict[str, list[str]] = {
    "python": ["python3", "python", "py"],
    "javascript": ["node", "deno", "bun"],
    "typescript": ["deno", "ts-node", "bun"],
    "java": ["java"],
    "go": ["go"],
}


def detect_language(file_path: Path) -> str | None:
    """
    Detect the programming language of a file.

    Tries in order:
    1. File extension mapping
    2. Shebang line analysis
    3. Content heuristics

    Returns the language identifier string or None if unknown.
    """
    # 1. Extension-based detection
    ext = file_path.suffix.lower()
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]

    # 2. Shebang-based detection
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline(256).strip()

        if first_line.startswith("#!"):
            shebang = first_line.lstrip("#!").strip()
            # Handle "#!/usr/bin/env python3" style
            parts = shebang.split()
            executable = parts[-1] if parts else ""
            exe_name = Path(executable).name

            for key, lang in SHEBANG_MAP.items():
                if key in exe_name:
                    return lang
    except (OSError, UnicodeDecodeError):
        pass

    return None


def detect_language_from_files(files: list[Path]) -> str | None:
    """
    Detect the dominant language from a collection of files.

    Returns the most common language detected across all files.
    """
    if not files:
        return None

    language_counts: dict[str, int] = {}
    for f in files:
        lang = detect_language(f)
        if lang and lang in SOURCE_LANGUAGES:
            language_counts[lang] = language_counts.get(lang, 0) + 1

    if not language_counts:
        return None

    return max(language_counts, key=language_counts.get)  # type: ignore[arg-type]


def detect_data_format(file_path: Path) -> str | None:
    """Detect the data format of a file from its extension."""
    ext = file_path.suffix.lower()
    lang = EXTENSION_MAP.get(ext)
    if lang and lang in DATA_FORMATS:
        return lang
    return None


def is_source_file(file_path: Path) -> bool:
    """Check if a file is a recognized source code file."""
    lang = detect_language(file_path)
    return lang is not None and lang in SOURCE_LANGUAGES


def is_data_file(file_path: Path) -> bool:
    """Check if a file is a recognized data format file."""
    lang = detect_language(file_path)
    return lang is not None and lang in DATA_FORMATS


def find_compiler(language: str) -> str | None:
    """
    Find an available compiler for the given language.

    Returns the path/name of the first available compiler, or None.
    """
    candidates = COMPILER_MAP.get(language, [])
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return None


def find_runtime(language: str) -> str | None:
    """
    Find an available runtime for the given language.

    Returns the path/name of the first available runtime, or None.
    """
    candidates = RUNTIME_MAP.get(language, [])
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return None


def get_source_extensions(language: str) -> list[str]:
    """Get all file extensions associated with a language."""
    return [ext for ext, lang in EXTENSION_MAP.items() if lang == language]


def detect_available_tools() -> dict[str, dict[str, str | None]]:
    """
    Detect all available compilers and runtimes on the system.

    Returns a dict of language → {"compiler": ..., "runtime": ...}.
    """
    tools: dict[str, dict[str, str | None]] = {}

    all_languages = set(list(COMPILER_MAP.keys()) + list(RUNTIME_MAP.keys()))
    for lang in sorted(all_languages):
        tools[lang] = {
            "compiler": find_compiler(lang),
            "runtime": find_runtime(lang),
        }

    return tools
