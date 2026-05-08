"""JSON file merger plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from amalgamator.data.base import DataMerger, MergeResult, MergeConflict, deep_merge_dicts
from amalgamator.data.registry import DataRegistry


class JsonMerger(DataMerger):
    """Merges multiple JSON files into one."""

    name = "json"
    extensions = [".json"]

    def load(self, file_path: Path) -> Any:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def dump(self, data: Any, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def merge(self, datasets: list[tuple[Path, Any]], strategy: str = "deep") -> MergeResult:
        if not datasets:
            return MergeResult(data={})

        if strategy == "concat":
            return self._merge_concat(datasets)

        # Deep or shallow merge (for dicts)
        all_conflicts: list[MergeConflict] = []
        result = datasets[0][1]

        for path, data in datasets[1:]:
            if isinstance(result, dict) and isinstance(data, dict):
                if strategy == "deep":
                    result, conflicts = deep_merge_dicts(result, data, source=str(path.name))
                else:  # shallow
                    conflicts = []
                    for key in data:
                        if key in result and result[key] != data[key]:
                            conflicts.append(MergeConflict(key, result[key], data[key], "previous", str(path.name)))
                    result.update(data)
                all_conflicts.extend(conflicts)
            elif isinstance(result, list) and isinstance(data, list):
                result = result + data
            else:
                result = data

        return MergeResult(data=result, conflicts=all_conflicts)

    def _merge_concat(self, datasets: list[tuple[Path, Any]]) -> MergeResult:
        """Concatenate all datasets into an array."""
        result = []
        for _, data in datasets:
            if isinstance(data, list):
                result.extend(data)
            else:
                result.append(data)
        return MergeResult(data=result)


DataRegistry.register(JsonMerger())
