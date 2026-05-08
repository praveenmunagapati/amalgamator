"""
Config loader — reads amalgamator.toml project configuration files.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import]
    except ImportError:
        import tomli as tomllib  # type: ignore[import,no-redef]


CONFIG_FILENAME = "amalgamator.toml"

DEFAULT_CONFIG_TEMPLATE = '''\
# Amalgamator Configuration
# https://github.com/amalgamator

[project]
name = "my-project"
# language = "c"          # auto-detected if omitted
# entry = "src/main.c"    # entry point file

[compiler]
# command = "gcc"          # auto-detected if omitted
# flags = ["-O2", "-Wall"]

[output]
# file = "build/amalgamated.c"
# compiled = "build/my-project"

[exclude]
patterns = [
    "test_*",
    "tests/",
    "*_test.*",
    "*.bak",
    "*.tmp",
]

[data]
# format = "json"
# merge_strategy = "deep"  # "deep", "shallow", "concat"
'''


@dataclass
class ProjectConfig:
    """Parsed project configuration."""

    # Project
    name: str = ""
    language: str | None = None
    entry: str | None = None

    # Compiler
    compiler_command: str | None = None
    compiler_flags: list[str] = field(default_factory=list)

    # Output
    output_file: str | None = None
    output_compiled: str | None = None

    # Exclusions
    exclude_patterns: list[str] = field(default_factory=list)

    # Data merging
    data_format: str | None = None
    merge_strategy: str = "deep"

    # Source path
    config_path: Path | None = None

    def to_dict(self) -> dict:
        """Convert config to a display-friendly dict."""
        return {
            "project": {
                "name": self.name,
                "language": self.language or "auto-detect",
                "entry": self.entry or "auto-detect",
            },
            "compiler": {
                "command": self.compiler_command or "auto-detect",
                "flags": self.compiler_flags,
            },
            "output": {
                "file": self.output_file or "auto",
                "compiled": self.output_compiled or "auto",
            },
            "exclude": {
                "patterns": self.exclude_patterns,
            },
            "data": {
                "format": self.data_format,
                "merge_strategy": self.merge_strategy,
            },
        }


def load_config(directory: Path) -> ProjectConfig:
    """
    Load configuration from amalgamator.toml in the given directory.

    Falls back to defaults if the file doesn't exist.
    """
    config_path = directory / CONFIG_FILENAME

    if not config_path.exists():
        return ProjectConfig()

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to parse {config_path}: {e}") from e

    return _parse_config(data, config_path)


def create_config(directory: Path) -> Path:
    """Create a default amalgamator.toml in the given directory."""
    config_path = directory / CONFIG_FILENAME

    if config_path.exists():
        raise FileExistsError(f"Config file already exists: {config_path}")

    config_path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    return config_path


def _parse_config(data: dict, config_path: Path) -> ProjectConfig:
    """Parse raw TOML data into a ProjectConfig."""
    project = data.get("project", {})
    compiler = data.get("compiler", {})
    output = data.get("output", {})
    exclude = data.get("exclude", {})
    data_section = data.get("data", {})

    return ProjectConfig(
        name=project.get("name", ""),
        language=project.get("language"),
        entry=project.get("entry"),
        compiler_command=compiler.get("command"),
        compiler_flags=compiler.get("flags", []),
        output_file=output.get("file"),
        output_compiled=output.get("compiled"),
        exclude_patterns=exclude.get("patterns", []),
        data_format=data_section.get("format"),
        merge_strategy=data_section.get("merge_strategy", "deep"),
        config_path=config_path,
    )
