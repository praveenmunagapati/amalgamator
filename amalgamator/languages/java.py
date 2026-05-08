"""
Java language plugin — handles import resolution and virtual amalgamation.

Java doesn't support true single-file amalgamation well due to its
one-public-class-per-file convention. This plugin uses "virtual amalgamation"
where files are collected and compiled together.
"""

from __future__ import annotations

import re
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.utils.detection import find_compiler, find_runtime

RE_IMPORT = re.compile(r"^\s*import\s+([\w.]+(?:\.\*)?)\s*;", re.MULTILINE)
RE_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)


class JavaPlugin(LanguagePlugin):
    """Java language plugin (virtual amalgamation)."""

    name = "java"
    extensions = [".java"]
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
            match = RE_IMPORT.match(line)
            if match:
                full_import = match.group(1)
                # Skip java.*, javax.*, standard library
                top = full_import.split(".")[0]
                if top not in ("java", "javax", "sun", "com", "org"):
                    imports.append(ImportInfo(
                        raw_line=line.strip(),
                        import_name=full_import,
                        is_local=True,
                        line_number=i,
                    ))
        return imports

    def resolve_import_path(self, import_info, source_file, search_paths) -> Path | None:
        parts = import_info.import_name.replace(".*", "").split(".")
        for search_dir in search_paths:
            candidate = search_dir / "/".join(parts)
            java_file = candidate.with_suffix(".java")
            if java_file.is_file():
                return java_file.resolve()
        return None

    def get_compile_command(self, source, output, flags, compiler=None) -> list[str]:
        cc = compiler or find_compiler("java") or "javac"
        cmd = [cc]
        if output:
            cmd.extend(["-d", str(output.parent)])
        cmd.extend(flags)
        cmd.append(str(source))
        return cmd

    def get_run_command(self, executable, args, runtime=None) -> list[str]:
        rt = runtime or find_runtime("java") or "java"
        class_name = executable.stem
        return [rt, "-cp", str(executable.parent), class_name] + args


LanguageRegistry.register(JavaPlugin())
