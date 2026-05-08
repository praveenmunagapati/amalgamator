"""
Go language plugin — handles import resolution and virtual amalgamation.
"""

from __future__ import annotations

import re
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.utils.detection import find_compiler, find_runtime

RE_IMPORT_SINGLE = re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE)
RE_IMPORT_BLOCK = re.compile(r"import\s*\((.*?)\)", re.DOTALL)
RE_IMPORT_LINE = re.compile(r'"([^"]+)"')


class GoPlugin(LanguagePlugin):
    """Go language plugin (virtual amalgamation)."""

    name = "go"
    extensions = [".go"]
    comment_prefix = "//"
    comment_block = ("/*", "*/")
    is_compiled = True

    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        imports: list[ImportInfo] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return imports

        # Single imports
        for match in RE_IMPORT_SINGLE.finditer(content):
            pkg = match.group(1)
            if self._is_local_package(pkg):
                imports.append(ImportInfo(
                    raw_line=match.group(0).strip(),
                    import_name=pkg,
                    is_local=True,
                ))

        # Block imports
        for block_match in RE_IMPORT_BLOCK.finditer(content):
            block = block_match.group(1)
            for line_match in RE_IMPORT_LINE.finditer(block):
                pkg = line_match.group(1)
                if self._is_local_package(pkg):
                    imports.append(ImportInfo(
                        raw_line=f'import "{pkg}"',
                        import_name=pkg,
                        is_local=True,
                    ))

        return imports

    def resolve_import_path(self, import_info, source_file, search_paths) -> Path | None:
        pkg_name = import_info.import_name.split("/")[-1]
        for search_dir in search_paths:
            candidate = search_dir / pkg_name
            if candidate.is_dir():
                # Find main .go file in the package
                for go_file in sorted(candidate.glob("*.go")):
                    return go_file.resolve()
            candidate = search_dir / f"{pkg_name}.go"
            if candidate.is_file():
                return candidate.resolve()
        return None

    def get_compile_command(self, source, output, flags, compiler=None) -> list[str]:
        cc = compiler or find_compiler("go") or "go"
        cmd = [cc, "build"]
        if output:
            cmd.extend(["-o", str(output)])
        cmd.extend(flags)
        cmd.append(str(source))
        return cmd

    def get_run_command(self, executable, args, runtime=None) -> list[str]:
        rt = runtime or find_runtime("go") or "go"
        return [rt, "run", str(executable)] + args

    @staticmethod
    def _is_local_package(pkg: str) -> bool:
        """Heuristic: local packages often start with ./ or contain the project module path."""
        if pkg.startswith("./") or pkg.startswith("../"):
            return True
        # Standard library packages don't contain dots in first segment
        first = pkg.split("/")[0]
        return "." in first


LanguageRegistry.register(GoPlugin())
