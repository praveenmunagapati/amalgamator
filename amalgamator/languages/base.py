"""
Abstract base class for language plugins.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ImportInfo:
    """Represents a parsed import/include statement."""
    raw_line: str           # Original line text
    import_name: str        # Module/file name being imported
    is_local: bool = True   # True if local (vs system/third-party)
    line_number: int = 0    # Line number in source file
    names: list[str] | None = None  # Specific names imported (from X import a, b)


class LanguagePlugin(ABC):
    """
    Abstract base class for language-specific amalgamation plugins.

    Each plugin handles:
    - Parsing import/include statements
    - Resolving import paths to actual files
    - Stripping already-merged imports
    - Building compile and run commands
    """

    name: str = ""
    extensions: list[str] = []
    comment_prefix: str = "//"
    comment_block: tuple[str, str] = ("/*", "*/")
    is_compiled: bool = True

    @abstractmethod
    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        """
        Extract all import/include statements from a file.

        Returns only local/project imports (not system or third-party).
        """
        ...

    @abstractmethod
    def resolve_import_path(
        self,
        import_info: ImportInfo,
        source_file: Path,
        search_paths: list[Path],
    ) -> Path | None:
        """
        Resolve an import to an actual file path.

        Returns None if the import can't be resolved to a local file.
        """
        ...

    @abstractmethod
    def get_compile_command(
        self,
        source: Path,
        output: Path | None,
        flags: list[str],
        compiler: str | None = None,
    ) -> list[str]:
        """Build the compile command for this language."""
        ...

    @abstractmethod
    def get_run_command(
        self,
        executable: Path,
        args: list[str],
        runtime: str | None = None,
    ) -> list[str]:
        """Build the run command for this language."""
        ...

    def should_strip_import(
        self,
        line: str,
        merged_files: set[Path],
        source_file: Path,
        search_paths: list[Path],
    ) -> bool:
        """
        Check if an import line should be stripped (because the file is already merged).

        Default implementation parses the line and checks against merged_files.
        """
        # Try to parse as an import
        stripped = line.strip()
        if not stripped:
            return False

        # Check each merged file against what this line might import
        for imp in self.extract_imports_from_line(stripped, source_file):
            resolved = self.resolve_import_path(imp, source_file, search_paths)
            if resolved and resolved in merged_files:
                return True

        return False

    def extract_imports_from_line(
        self, line: str, source_file: Path
    ) -> list[ImportInfo]:
        """
        Extract import info from a single line (helper for import stripping).

        Default: returns empty. Override for per-line parsing.
        """
        return []

    def wrap_section(self, content: str, file_path: Path) -> str:
        """
        Optionally wrap a file's content for namespace safety.

        Default: no wrapping. Override for languages that need it (e.g., Python, JS).
        """
        return content

    def get_default_output_extension(self) -> str:
        """Get the default output file extension for amalgamated output."""
        if self.extensions:
            return self.extensions[0]
        return ".txt"

    def get_section_comment(self, rel_path: str) -> str:
        """Generate a section marker comment for the amalgamated file."""
        sep = "─" * 50
        return (
            f"\n{self.comment_prefix} {sep}\n"
            f"{self.comment_prefix} ══════ {rel_path} ══════\n"
            f"{self.comment_prefix} {sep}\n"
        )
