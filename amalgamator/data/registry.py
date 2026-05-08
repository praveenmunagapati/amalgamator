"""Data format merger registry."""

from __future__ import annotations

from amalgamator.data.base import DataMerger


class DataRegistry:
    """Registry of available data format mergers."""

    _mergers: dict[str, DataMerger] = {}

    @classmethod
    def register(cls, merger: DataMerger) -> None:
        cls._mergers[merger.name] = merger
        for ext in merger.extensions:
            cls._mergers[ext.lstrip(".")] = merger

    @classmethod
    def get(cls, name: str) -> DataMerger | None:
        cls._ensure_loaded()
        return cls._mergers.get(name)

    @classmethod
    def available(cls) -> list[str]:
        cls._ensure_loaded()
        seen = set()
        names = []
        for m in cls._mergers.values():
            if m.name not in seen:
                seen.add(m.name)
                names.append(m.name)
        return sorted(names)

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._mergers:
            return
        try:
            from amalgamator.data import json_merger  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.data import xml_merger  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.data import yaml_merger  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.data import toml_merger  # noqa: F401
        except ImportError:
            pass
