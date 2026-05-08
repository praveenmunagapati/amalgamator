"""XML file merger plugin."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from amalgamator.data.base import DataMerger, MergeResult, MergeConflict
from amalgamator.data.registry import DataRegistry


class XmlMerger(DataMerger):
    """Merges multiple XML files by combining children under a common root."""

    name = "xml"
    extensions = [".xml"]

    def load(self, file_path: Path) -> Any:
        tree = ET.parse(file_path)
        return tree.getroot()

    def dump(self, data: Any, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tree = ET.ElementTree(data)
        ET.indent(tree, space="  ")
        tree.write(output_path, encoding="unicode", xml_declaration=True)

    def merge(self, datasets: list[tuple[Path, Any]], strategy: str = "deep") -> MergeResult:
        if not datasets:
            root = ET.Element("root")
            return MergeResult(data=root)

        conflicts: list[MergeConflict] = []
        base_path, base_root = datasets[0]
        # Use a copy of the first root
        merged = ET.Element(base_root.tag, base_root.attrib)
        for child in base_root:
            merged.append(child)

        for path, root in datasets[1:]:
            if root.tag != merged.tag:
                conflicts.append(MergeConflict(
                    key_path="root_tag",
                    value_a=merged.tag,
                    value_b=root.tag,
                    file_a=str(base_path.name),
                    file_b=str(path.name),
                ))
            # Merge attributes (overlay wins)
            for attr_key, attr_val in root.attrib.items():
                if attr_key in merged.attrib and merged.attrib[attr_key] != attr_val:
                    conflicts.append(MergeConflict(
                        key_path=f"@{attr_key}",
                        value_a=merged.attrib[attr_key],
                        value_b=attr_val,
                        file_a=str(base_path.name),
                        file_b=str(path.name),
                    ))
                merged.set(attr_key, attr_val)

            # Add all child elements
            for child in root:
                merged.append(child)

        return MergeResult(data=merged, conflicts=conflicts)


DataRegistry.register(XmlMerger())
