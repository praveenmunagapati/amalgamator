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

# ── Hardware-Aware Build Profiles ──
# [build.profiles.embedded]
# compiler = "arm-none-eabi-gcc"
# flags = ["-Os", "-mcpu=cortex-m3"]
# defines = ["MOTHERBOARD=BOARD_RAMPS_14"]
# includes = ["src/HAL/STM32"]
'''


@dataclass
class BuildProfile:
    """A hardware-aware build profile."""
    compiler: str | None = None
    flags: list[str] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    linker_flags: list[str] = field(default_factory=list)


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

    # Build Profiles
    profiles: dict[str, BuildProfile] = field(default_factory=dict)

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
        res = {
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
        if self.profiles:
            res["profiles"] = {k: vars(v) for k, v in self.profiles.items()}
        return res


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

    # Parse profiles
    profiles_dict: dict[str, BuildProfile] = {}
    build_section = data.get("build", {})
    if isinstance(build_section, dict):
        profiles_raw = build_section.get("profiles", {})
        if isinstance(profiles_raw, dict):
            for name, pdata in profiles_raw.items():
                profiles_dict[name] = BuildProfile(
                    compiler=pdata.get("compiler"),
                    flags=pdata.get("flags", []),
                    defines=pdata.get("defines", []),
                    includes=pdata.get("includes", []),
                    linker_flags=pdata.get("linker_flags", []),
                )

    return ProjectConfig(
        name=project.get("name", ""),
        language=project.get("language"),
        entry=project.get("entry"),
        compiler_command=compiler.get("command"),
        compiler_flags=compiler.get("flags", []),
        profiles=profiles_dict,
        output_file=output.get("file"),
        output_compiled=output.get("compiled"),
        exclude_patterns=exclude.get("patterns", []),
        data_format=data_section.get("format"),
        merge_strategy=data_section.get("merge_strategy", "deep"),
        config_path=config_path,
    )
