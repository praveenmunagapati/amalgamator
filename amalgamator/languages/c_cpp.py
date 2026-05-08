"""
C/C++ language plugin — handles #include resolution and amalgamation.

Inspired by SQLite's amalgamation technique: merges .c/.h files into a
single translation unit, stripping redundant local #include directives.
"""

from __future__ import annotations

import re
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.utils.detection import find_compiler

# ── Include parsing regex ────────────────────────────────────────────────────

# Matches: #include "local_file.h"  (local includes only, not <system.h>)
RE_INCLUDE_LOCAL = re.compile(
    r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE
)

# Matches: #pragma once
RE_PRAGMA_ONCE = re.compile(r"^\s*#\s*pragma\s+once\b")

# Matches: #ifndef GUARD / #define GUARD (traditional include guards)
RE_IFNDEF_GUARD = re.compile(r"^\s*#\s*ifndef\s+(\w+)")
RE_DEFINE_GUARD = re.compile(r"^\s*#\s*define\s+(\w+)")
RE_ENDIF = re.compile(r"^\s*#\s*endif")


class CCppPlugin(LanguagePlugin):
    """C/C++ language plugin for amalgamation."""

    name = "c"
    extensions = [".c", ".h", ".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh"]
    comment_prefix = "//"
    comment_block = ("/*", "*/")
    is_compiled = True

    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        """Extract #include "..." directives from a C/C++ file."""
        imports: list[ImportInfo] = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return imports

        for i, line in enumerate(content.splitlines(), 1):
            match = RE_INCLUDE_LOCAL.match(line)
            if match:
                include_path = match.group(1)
                imports.append(ImportInfo(
                    raw_line=line.strip(),
                    import_name=include_path,
                    is_local=True,
                    line_number=i,
                ))

        return imports

    def resolve_import_path(
        self,
        import_info: ImportInfo,
        source_file: Path,
        search_paths: list[Path],
    ) -> Path | None:
        """Resolve an #include path to an actual file."""
        include_name = import_info.import_name

        # Search in order: source file directory, then search paths
        for search_dir in search_paths:
            candidate = (search_dir / include_name).resolve()
            if candidate.is_file():
                return candidate

        return None

    def extract_imports_from_line(
        self, line: str, source_file: Path,
    ) -> list[ImportInfo]:
        """Extract import info from a single line."""
        match = RE_INCLUDE_LOCAL.match(line)
        if match:
            return [ImportInfo(
                raw_line=line,
                import_name=match.group(1),
                is_local=True,
            )]
        return []

    def get_compile_command(
        self,
        source: Path,
        output: Path | None,
        flags: list[str],
        compiler: str | None = None,
    ) -> list[str]:
        """Build gcc/g++/clang compile command."""
        # Determine if C or C++
        is_cpp = source.suffix.lower() in (".cpp", ".cxx", ".cc", ".hpp", ".hxx", ".hh")

        if compiler:
            cc = compiler
        elif is_cpp:
            cc = find_compiler("cpp") or "g++"
        else:
            cc = find_compiler("c") or "gcc"

        cmd = [cc]
        if output:
            cmd.extend(["-o", str(output)])

        # Default flags if none specified
        if not flags:
            flags = ["-Wall"]

        cmd.extend(flags)
        cmd.append(str(source))
        return cmd

    def get_run_command(
        self,
        executable: Path,
        args: list[str],
        runtime: str | None = None,
    ) -> list[str]:
        """Run the compiled binary directly."""
        return [str(executable)] + args

    def wrap_section(self, content: str, file_path: Path) -> str:
        """
        For header files: strip #pragma once and include guards that would
        conflict in the amalgamated file. The amalgamated file has its own
        structure so these are redundant.
        """
        if file_path.suffix.lower() not in (".h", ".hpp", ".hxx", ".hh"):
            return content

        lines = content.splitlines(keepends=True)
        result_lines: list[str] = []
        guard_name: str | None = None
        skip_endif = False

        i = 0
        while i < len(lines):
            line = lines[i]

            # Strip #pragma once
            if RE_PRAGMA_ONCE.match(line):
                i += 1
                continue

            # Strip include guard pair (#ifndef X / #define X)
            ifndef_match = RE_IFNDEF_GUARD.match(line)
            if ifndef_match and guard_name is None and i + 1 < len(lines):
                define_match = RE_DEFINE_GUARD.match(lines[i + 1])
                if define_match and define_match.group(1) == ifndef_match.group(1):
                    guard_name = ifndef_match.group(1)
                    skip_endif = True
                    i += 2
                    continue

            # Strip matching #endif at the very end
            if skip_endif and RE_ENDIF.match(line):
                # Only strip the last #endif — check if there's no more code after
                remaining = "".join(lines[i + 1:]).strip()
                if not remaining:
                    skip_endif = False
                    i += 1
                    continue

            result_lines.append(line)
            i += 1

        return "".join(result_lines)


# ── Self-register ────────────────────────────────────────────────────────────

_plugin = CCppPlugin()
LanguageRegistry.register(_plugin)

# Also register as "cpp" alias
_cpp_alias = CCppPlugin()
_cpp_alias.name = "cpp"
LanguageRegistry.register(_cpp_alias)
