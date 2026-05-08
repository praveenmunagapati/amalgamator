"""
Python language plugin — handles import resolution and amalgamation.

Parses `import module` and `from module import name` statements,
distinguishes local vs stdlib/third-party imports, and wraps modules
to avoid namespace collisions in the amalgamated file.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.utils.detection import find_runtime

# ── Import parsing patterns ──────────────────────────────────────────────────

RE_IMPORT = re.compile(r"^\s*import\s+([\w.]+)")
RE_FROM_IMPORT = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+)")

# Standard library module names (subset — enough for heuristic)
_STDLIB_TOP_LEVEL: set[str] | None = None


def _get_stdlib_modules() -> set[str]:
    """Get a set of standard library top-level module names."""
    global _STDLIB_TOP_LEVEL
    if _STDLIB_TOP_LEVEL is not None:
        return _STDLIB_TOP_LEVEL

    _STDLIB_TOP_LEVEL = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {
        "abc", "argparse", "ast", "asyncio", "base64", "bisect", "builtins",
        "calendar", "cmath", "codecs", "collections", "concurrent", "configparser",
        "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal",
        "difflib", "dis", "distutils", "email", "enum", "errno", "faulthandler",
        "fileinput", "fnmatch", "fractions", "functools", "gc", "getpass", "glob",
        "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib", "inspect",
        "io", "ipaddress", "itertools", "json", "keyword", "linecache", "locale",
        "logging", "lzma", "math", "mimetypes", "multiprocessing", "numbers",
        "operator", "os", "pathlib", "pickle", "pkgutil", "platform", "pprint",
        "profile", "pstats", "queue", "random", "re", "readline", "reprlib",
        "secrets", "select", "shelve", "shlex", "shutil", "signal", "site",
        "smtplib", "socket", "sqlite3", "ssl", "stat", "statistics", "string",
        "struct", "subprocess", "sys", "sysconfig", "tempfile", "textwrap",
        "threading", "time", "timeit", "tkinter", "token", "tokenize", "tomllib",
        "traceback", "types", "typing", "unicodedata", "unittest", "urllib",
        "uuid", "venv", "warnings", "wave", "weakref", "webbrowser", "xml",
        "xmlrpc", "zipfile", "zipimport", "zlib",
    }
    return _STDLIB_TOP_LEVEL


class PythonPlugin(LanguagePlugin):
    """Python language plugin for amalgamation."""

    name = "python"
    extensions = [".py", ".pyw"]
    comment_prefix = "#"
    comment_block = ('"""', '"""')
    is_compiled = False

    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        """Extract import statements from a Python file."""
        imports: list[ImportInfo] = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return imports

        # Use AST parsing for accuracy
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            # Fallback to regex
            return self._extract_imports_regex(content)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    if not self._is_stdlib_or_thirdparty(module):
                        imports.append(ImportInfo(
                            raw_line=f"import {alias.name}",
                            import_name=alias.name,
                            is_local=True,
                            line_number=node.lineno,
                        ))

            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    module = node.module.split(".")[0]
                    if not self._is_stdlib_or_thirdparty(module):
                        names = [a.name for a in node.names]
                        imports.append(ImportInfo(
                            raw_line=f"from {node.module} import {', '.join(names)}",
                            import_name=node.module,
                            is_local=True,
                            line_number=node.lineno,
                            names=names,
                        ))
                elif node.level > 0:
                    # Relative import — always local
                    module_name = node.module or ""
                    dots = "." * node.level
                    names = [a.name for a in node.names]
                    imports.append(ImportInfo(
                        raw_line=f"from {dots}{module_name} import {', '.join(names)}",
                        import_name=f"{dots}{module_name}",
                        is_local=True,
                        line_number=node.lineno,
                        names=names,
                    ))

        return imports

    def resolve_import_path(
        self,
        import_info: ImportInfo,
        source_file: Path,
        search_paths: list[Path],
    ) -> Path | None:
        """Resolve a Python import to a file path."""
        module_name = import_info.import_name.lstrip(".")

        # Handle relative imports
        if import_info.import_name.startswith("."):
            dots = len(import_info.import_name) - len(import_info.import_name.lstrip("."))
            base = source_file.parent
            for _ in range(dots - 1):
                base = base.parent
            if module_name:
                return self._find_module(module_name, [base])
            return None

        # Absolute import
        return self._find_module(module_name, search_paths)

    def _find_module(self, module_name: str, search_paths: list[Path]) -> Path | None:
        """Find a module file given search paths."""
        parts = module_name.split(".")

        for search_dir in search_paths:
            # Try as a direct .py file
            candidate = search_dir / "/".join(parts)
            py_file = candidate.with_suffix(".py")
            if py_file.is_file():
                return py_file.resolve()

            # Try as a package (__init__.py)
            init_file = candidate / "__init__.py"
            if init_file.is_file():
                return init_file.resolve()

        return None

    def extract_imports_from_line(
        self, line: str, source_file: Path,
    ) -> list[ImportInfo]:
        """Parse a single line for import statements."""
        match = RE_FROM_IMPORT.match(line)
        if match:
            return [ImportInfo(
                raw_line=line,
                import_name=match.group(1),
                is_local=True,
            )]

        match = RE_IMPORT.match(line)
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
        """Python is interpreted — use py_compile for syntax check."""
        rt = compiler or find_runtime("python") or "python"
        return [rt, "-m", "py_compile", str(source)]

    def get_run_command(
        self,
        executable: Path,
        args: list[str],
        runtime: str | None = None,
    ) -> list[str]:
        """Run with the Python interpreter."""
        rt = runtime or find_runtime("python") or "python"
        return [rt, str(executable)] + args

    def wrap_section(self, content: str, file_path: Path) -> str:
        """
        Wrap a Python module's content.

        For now, we add a comment marker but don't namespace-wrap,
        because Python's import system makes true amalgamation complex.
        The merged file is intended to be self-contained.
        """
        return content

    def _extract_imports_regex(self, content: str) -> list[ImportInfo]:
        """Fallback regex-based import extraction."""
        imports: list[ImportInfo] = []
        for i, line in enumerate(content.splitlines(), 1):
            for info in self.extract_imports_from_line(line, Path(".")):
                info.line_number = i
                module = info.import_name.split(".")[0]
                if not self._is_stdlib_or_thirdparty(module):
                    imports.append(info)
        return imports

    @staticmethod
    def _is_stdlib_or_thirdparty(module_name: str) -> bool:
        """Heuristic: check if a top-level module name is stdlib."""
        return module_name in _get_stdlib_modules()


# ── Self-register ────────────────────────────────────────────────────────────

LanguageRegistry.register(PythonPlugin())
