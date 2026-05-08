"""
Abstract base class for data format merger plugins.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class MergeConflict:
    """Represents a key conflict during merge."""

    def __init__(self, key_path: str, value_a: Any, value_b: Any, file_a: str, file_b: str):
        self.key_path = key_path
        self.value_a = value_a
        self.value_b = value_b
        self.file_a = file_a
        self.file_b = file_b

    def __str__(self) -> str:
        return f"Conflict at '{self.key_path}': {self.file_a} vs {self.file_b}"


class MergeResult:
    """Result of a data merge operation."""

    def __init__(self, data: Any, conflicts: list[MergeConflict] | None = None):
        self.data = data
        self.conflicts = conflicts or []

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0


class DataMerger(ABC):
    """Abstract base class for data format mergers."""

    name: str = ""
    extensions: list[str] = []

    @abstractmethod
    def load(self, file_path: Path) -> Any:
        """Load a data file and return the parsed data."""
        ...

    @abstractmethod
    def dump(self, data: Any, output_path: Path) -> None:
        """Write merged data to a file."""
        ...

    @abstractmethod
    def merge(self, datasets: list[tuple[Path, Any]], strategy: str = "deep") -> MergeResult:
        """
        Merge multiple datasets into one.

        Args:
            datasets: List of (source_path, parsed_data) tuples.
            strategy: "deep" (recursive merge), "shallow" (top-level merge),
                      or "concat" (array concatenation).

        Returns:
            MergeResult with merged data and any conflicts.
        """
        ...

    def merge_files(self, files: list[Path], strategy: str = "deep") -> MergeResult:
        """Load and merge multiple files."""
        datasets: list[tuple[Path, Any]] = []
        for f in files:
            data = self.load(f)
            datasets.append((f, data))
        return self.merge(datasets, strategy)


def deep_merge_dicts(base: dict, overlay: dict, path: str = "", source: str = "") -> tuple[dict, list[MergeConflict]]:
    """
    Deep merge two dicts. Overlay values win on conflict.

    Returns (merged_dict, list_of_conflicts).
    """
    result = dict(base)
    conflicts: list[MergeConflict] = []

    for key, value in overlay.items():
        key_path = f"{path}.{key}" if path else key

        if key in result:
            if isinstance(result[key], dict) and isinstance(value, dict):
                merged, sub_conflicts = deep_merge_dicts(result[key], value, key_path, source)
                result[key] = merged
                conflicts.extend(sub_conflicts)
            elif isinstance(result[key], list) and isinstance(value, list):
                result[key] = result[key] + value
            elif result[key] != value:
                conflicts.append(MergeConflict(
                    key_path=key_path,
                    value_a=result[key],
                    value_b=value,
                    file_a="previous",
                    file_b=source,
                ))
                result[key] = value  # Last wins
        else:
            result[key] = value

    return result, conflicts
