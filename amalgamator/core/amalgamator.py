"""
Amalgamator core — the merge engine that combines source files into a single file.

Supports:
- Import stripping (removes already-merged imports)
- #line directives for C/C++ source mapping
- Source map file generation for all languages
- Entry point reordering (ensures entry point is last)
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from amalgamator import __version__


class AmalgamationResult:
    """Result of an amalgamation operation."""

    def __init__(self, output_path: Path, source_files: list[Path], content: str,
                 source_map: dict | None = None) -> None:
        self.output_path = output_path
        self.source_files = source_files
        self.content = content
        self.file_count = len(source_files)
        self.source_map = source_map

    @property
    def output_size(self) -> int:
        return len(self.content.encode("utf-8"))


@dataclass
class SourceMapEntry:
    """Maps a range of amalgamated lines back to the original file."""
    amalgamated_start: int
    amalgamated_end: int
    original_file: str
    original_start: int
    original_end: int


class MergeEngine:
    """
    Core merge engine that amalgamates ordered source files into a single file.

    The engine takes files in dependency-resolved order and concatenates them
    with section markers, header metadata, and language-specific transformations.
    """

    def __init__(
        self,
        language: str,
        comment_prefix: str = "//",
        comment_block: tuple[str, str] | None = None,
        strip_imports_fn=None,
        wrap_section_fn=None,
        line_directive_fn=None,
        emit_line_directives: bool = True,
    ) -> None:
        """
        Args:
            language: Language identifier.
            comment_prefix: Single-line comment prefix (e.g., "//", "#").
            comment_block: Block comment delimiters (e.g., ("/*", "*/")).
            strip_imports_fn: Callable(line, merged_files, source_file, search_paths) -> str|None
                              Returns None to strip, or the (possibly modified) line to keep.
            wrap_section_fn: Callable(content, file_path) -> str
            line_directive_fn: Callable(line_number, file_path) -> str|None
                               Returns a #line directive or None.
            emit_line_directives: If True and line_directive_fn is set, emit directives.
        """
        self.language = language
        self.comment_prefix = comment_prefix
        self.comment_block = comment_block or (f"{comment_prefix} ", "")
        self.strip_imports_fn = strip_imports_fn
        self.wrap_section_fn = wrap_section_fn
        self.line_directive_fn = line_directive_fn
        self.emit_line_directives = emit_line_directives

    def amalgamate(
        self,
        ordered_files: list[Path],
        output_path: Path,
        base_path: Path | None = None,
        extra_header: str | None = None,
        write_source_map: bool = True,
    ) -> AmalgamationResult:
        """
        Merge ordered files into a single amalgamated file.

        Args:
            ordered_files: Files in dependency order (dependencies first).
            output_path: Path to write the amalgamated file.
            base_path: Base path for relative path display in headers.
            extra_header: Extra text to include in the file header.
            write_source_map: If True, write a .map.json source map file.

        Returns:
            AmalgamationResult with output details and source map.
        """
        if not ordered_files:
            raise ValueError("No files to amalgamate.")

        if search_paths is None:
            search_paths = [base_path]

        sections: list[str] = []
        source_map_entries: list[dict[str, Any]] = []
        current_line = 1  # Track line numbers in the amalgamated file

        # 1. Generate header
        header = self._generate_header(ordered_files, base_path, extra_header)
        sections.append(header)
        current_line += header.count("\n") + 1

        # 2. Track merged files for import stripping
        merged_files: set[Path] = set()

        # 3. Process each file
        for file_path in ordered_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                # Error recovery: skip unreadable files with a warning comment
                error_msg = f"{self.comment_prefix} ERROR: Could not read {file_path}: {e}"
                sections.append(f"\n{error_msg}\n")
                current_line += 3
                continue

            original_line_count = len(content.splitlines())

            # Strip imports for already-merged files
            if self.strip_imports_fn:
                lines = content.splitlines(keepends=True)
                filtered_lines = []
                for line in lines:
                    result = self.strip_imports_fn(line, merged_files, file_path, search_paths)
                    if result is not None:
                        filtered_lines.append(result)
                content = "".join(filtered_lines)

            # Wrap section if needed (e.g., Python namespace wrapping)
            if self.wrap_section_fn:
                content = self.wrap_section_fn(content, file_path)

            # Add section marker
            rel_path = _relative_display(file_path, base_path)
            section_header = self._format_section_header(rel_path)
            section_header_lines = section_header.count("\n") + 1

            # Emit #line directive if supported
            line_directive = ""
            if self.emit_line_directives and self.line_directive_fn:
                directive = self.line_directive_fn(1, file_path)
                if directive:
                    line_directive = f"\n{directive}\n"

            section = f"{section_header}{line_directive}\n{content}\n"
            sections.append(section)

            # Track source map
            content_start = current_line + section_header_lines + (2 if line_directive else 1)
            content_end = content_start + len(content.splitlines()) - 1
            source_map_entries.append({
                "file": rel_path,
                "amalgamated_lines": [content_start, content_end],
                "original_lines": [1, original_line_count],
            })

            current_line += section.count("\n") + 1
            merged_files.add(file_path)

        # 4. Join and write
        amalgamated = "\n".join(sections)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(amalgamated, encoding="utf-8")

        # 5. Write source map
        source_map = {
            "version": 1,
            "generator": f"Amalgamator v{__version__}",
            "language": self.language,
            "output": str(output_path.name),
            "files": [_relative_display(f, base_path) for f in ordered_files],
            "mappings": source_map_entries,
        }

        if write_source_map:
            map_path = output_path.with_suffix(output_path.suffix + ".map.json")
            map_path.write_text(json.dumps(source_map, indent=2), encoding="utf-8")

        return AmalgamationResult(
            output_path=output_path,
            source_files=ordered_files,
            content=amalgamated,
            source_map=source_map,
        )

    def _generate_header(
        self,
        files: list[Path],
        base_path: Path,
        extra: str | None,
    ) -> str:
        """Generate the amalgamated file header comment block."""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        base_display = str(base_path).replace("\\", "/")
        cp = self.comment_prefix

        lines = [
            f"{cp} {'=' * 60}",
            f"{cp}  AMALGAMATED FILE",
            f"{cp}  Generated by Amalgamator v{__version__}",
            f"{cp}  Date: {now}",
            f"{cp}  Language: {self.language}",
            f"{cp}  Source files: {len(files)}",
            f"{cp}  Source directory: {base_display}",
        ]

        if extra:
            lines.append(f"{cp}")
            for extra_line in extra.splitlines():
                lines.append(f"{cp}  {extra_line}")

        lines.append(f"{cp}")
        lines.append(f"{cp}  Files (in merge order):")
        for f in files:
            rel = _relative_display(f, base_path)
            lines.append(f"{cp}    - {rel}")

        lines.append(f"{cp} {'=' * 60}")
        return "\n".join(lines)

    def _format_section_header(self, rel_path: str) -> str:
        """Format a section header (without the content)."""
        separator = f"{self.comment_prefix} {'─' * 50}"
        header = f"{self.comment_prefix} ══════ {rel_path} ══════"
        return f"\n{separator}\n{header}\n{separator}"


def _relative_display(file_path: Path, base_path: Path) -> str:
    """Get a display-friendly relative path."""
    try:
        return str(file_path.relative_to(base_path)).replace("\\", "/")
    except ValueError:
        return str(file_path).replace("\\", "/")


def reorder_with_entry_point(
    ordered_files: list[Path],
    entry_point: Path,
) -> list[Path]:
    """
    Ensure the entry point file is last in the merge order.

    The entry point (containing main()) should be the last file
    so that all dependencies are defined before it.
    """
    if entry_point not in ordered_files:
        return ordered_files

    result = [f for f in ordered_files if f != entry_point]
    result.append(entry_point)
    return result
