"""Data format merger plugins for JSON, XML, YAML, and TOML amalgamation."""

from amalgamator.data.base import DataMerger
from amalgamator.data.registry import DataRegistry

__all__ = ["DataMerger", "DataRegistry"]
