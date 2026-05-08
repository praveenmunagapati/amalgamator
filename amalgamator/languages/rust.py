"""
Rust language plugin — handles use/mod resolution and amalgamation.
"""

from __future__ import annotations

import re
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.utils.detection import find_compiler

RE_MOD = re.compile(r"^\s*mod\s+(\w+)\s*;", re.MULTILINE)
RE_USE = re.compile(r"^\s*use\s+(?:crate::)?(\w[\w:]*)", re.MULTILINE)


class RustPlugin(LanguagePlugin):
    """Rust language plugin for amalgamation."""

    name = "rust"
    extensions = [".rs"]
    comment_prefix = "//"
    comment_block = ("/*", "*/")
    is_compiled = True

    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        imports: list[ImportInfo] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return imports

        for i, line in enumerate(content.splitlines(), 1):
            match = RE_MOD.match(line)
            if match:
                imports.append(ImportInfo(
                    raw_line=line.strip(),
                    import_name=match.group(1),
                    is_local=True,
                    line_number=i,
                ))
        return imports

    def resolve_import_path(self, import_info, source_file, search_paths) -> Path | None:
        mod_name = import_info.import_name
        for search_dir in search_paths:
            # mod foo; -> foo.rs or foo/mod.rs
            candidate = search_dir / f"{mod_name}.rs"
            if candidate.is_file():
                return candidate.resolve()
            candidate = search_dir / mod_name / "mod.rs"
            if candidate.is_file():
                return candidate.resolve()
        return None

    def get_compile_command(self, source, output, flags, compiler=None) -> list[str]:
        cc = compiler or find_compiler("rust") or "rustc"
        cmd = [cc]
        if output:
            cmd.extend(["-o", str(output)])
        cmd.extend(flags)
        cmd.append(str(source))
        return cmd

    def get_run_command(self, executable, args, runtime=None) -> list[str]:
        return [str(executable)] + args


LanguageRegistry.register(RustPlugin())
