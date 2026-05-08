"""TOML file merger plugin."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import]
    except ImportError:
        import tomli as tomllib  # type: ignore[import,no-redef]

from amalgamator.data.base import DataMerger, MergeResult, MergeConflict, deep_merge_dicts
from amalgamator.data.registry import DataRegistry


class TomlMerger(DataMerger):
    """Merges multiple TOML files into one."""

    name = "toml"
    extensions = [".toml"]

    def load(self, file_path: Path) -> Any:
        with open(file_path, "rb") as f:
            return tomllib.load(f)

    def dump(self, data: Any, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # tomllib is read-only; write manually as TOML
        with open(output_path, "w", encoding="utf-8") as f:
            _write_toml(data, f)

    def merge(self, datasets: list[tuple[Path, Any]], strategy: str = "deep") -> MergeResult:
        if not datasets:
            return MergeResult(data={})

        all_conflicts: list[MergeConflict] = []
        result = datasets[0][1]

        for path, data in datasets[1:]:
            if isinstance(result, dict) and isinstance(data, dict):
                result, conflicts = deep_merge_dicts(result, data, source=str(path.name))
                all_conflicts.extend(conflicts)
            else:
                result = data

        return MergeResult(data=result, conflicts=all_conflicts)


def _write_toml(data: dict, f, prefix: str = "") -> None:
    """Simple TOML writer for merged output."""
    # Write simple key-value pairs first
    for key, value in data.items():
        if isinstance(value, dict):
            continue
        f.write(f"{key} = {_toml_value(value)}\n")

    # Write tables
    for key, value in data.items():
        if isinstance(value, dict):
            table_key = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            f.write(f"\n[{table_key}]\n")
            _write_toml(value, f, table_key)


def _toml_value(value: Any) -> str:
    """Convert a Python value to a TOML string representation."""
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        items = ", ".join(_toml_value(v) for v in value)
        return f"[{items}]"
    return f'"{value}"'


DataRegistry.register(TomlMerger())
