"""
C/C++ language plugin — handles #include resolution and amalgamation.

Inspired by SQLite's amalgamation technique: merges .c/.h files into a
single translation unit, stripping redundant local #include directives
and emitting #line directives for accurate error reporting.
"""

from __future__ import annotations

import re
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.languages.preprocessor import CPreprocessor
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

# Matches: int main( or void main(
RE_MAIN_FUNC = re.compile(r"^\s*(?:int|void)\s+main\s*\(", re.MULTILINE)


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

        preprocessor = CPreprocessor(self.defines)

        for i, line in enumerate(content.splitlines(), 1):
            is_active = preprocessor.process_line(line)
            if not is_active:
                continue

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

    def detect_entry_point(self, files: list[Path]) -> Path | None:
        """
        Auto-detect the entry point by finding the file containing main().

        Searches for `int main(` or `void main(` patterns. Only considers
        .c/.cpp files (not headers).
        """
        source_exts = {".c", ".cpp", ".cxx", ".cc"}

        for file_path in files:
            if file_path.suffix.lower() not in source_exts:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if RE_MAIN_FUNC.search(content):
                    return file_path
            except OSError:
                continue

        return None

    def generate_line_directive(self, line_number: int, file_path: Path) -> str | None:
        """
        Generate a C/C++ #line directive for source mapping.

        The compiler will use these to report errors in terms of the original
        source file and line number, not the amalgamated file.
        """
        # Use forward slashes for cross-platform compatibility
        display_path = str(file_path).replace("\\", "/")
        return f'#line {line_number} "{display_path}"'

    def get_compile_command(
        self,
        source: Path,
        output: Path | None,
        flags: list[str],
        compiler: str | None = None,
    ) -> list[str]:
        """Build gcc/g++/clang compile command."""
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
        Strip inactive preprocessor blocks based on profile defines,
        and strip #pragma once / include guards for header files.
        """
        # 1. Preprocessor evaluation (strip inactive blocks)
        preprocessor = CPreprocessor(self.defines)
        pp_lines = []
        for line in content.splitlines(keepends=True):
            if preprocessor.process_line(line):
                pp_lines.append(line)
            else:
                # Blank out to preserve line numbers for #line directives
                pp_lines.append("// [amalgamator: inactive]\n")
                
        content = "".join(pp_lines)

        # 2. Header guard stripping (only for headers)
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
