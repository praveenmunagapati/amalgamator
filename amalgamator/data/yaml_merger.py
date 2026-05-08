"""YAML file merger plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from amalgamator.data.base import DataMerger, MergeResult, MergeConflict, deep_merge_dicts
from amalgamator.data.registry import DataRegistry


class YamlMerger(DataMerger):
    """Merges multiple YAML files into one."""

    name = "yaml"
    extensions = [".yaml", ".yml"]

    def load(self, file_path: Path) -> Any:
        with open(file_path, "r", encoding="utf-8") as f:
            # Load all documents in a multi-doc YAML
            docs = list(yaml.safe_load_all(f))
            if len(docs) == 1:
                return docs[0]
            return docs

    def dump(self, data: Any, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def merge(self, datasets: list[tuple[Path, Any]], strategy: str = "deep") -> MergeResult:
        if not datasets:
            return MergeResult(data={})

        all_conflicts: list[MergeConflict] = []
        result = datasets[0][1]

        for path, data in datasets[1:]:
            if isinstance(result, dict) and isinstance(data, dict):
                if strategy == "deep":
                    result, conflicts = deep_merge_dicts(result, data, source=str(path.name))
                else:
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


DataRegistry.register(YamlMerger())
