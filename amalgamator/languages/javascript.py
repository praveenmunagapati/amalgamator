"""
JavaScript language plugin — handles require/import resolution and amalgamation.

Parses both CommonJS (require) and ESM (import/export) syntax.
Wraps modules in an IIFE pattern for the amalgamated output.
"""

from __future__ import annotations

import re
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.utils.detection import find_runtime

# ── Import parsing patterns ──────────────────────────────────────────────────

# CommonJS: require('./module'), require("./module")
RE_REQUIRE = re.compile(
    r"""require\s*\(\s*['"](\.[^'"]+)['"]\s*\)"""
)

# ESM: import X from './module'
RE_ESM_IMPORT = re.compile(
    r"""^\s*import\s+.+\s+from\s+['"](\.[^'"]+)['"]""", re.MULTILINE
)

# ESM: import './module' (side-effect import)
RE_ESM_IMPORT_BARE = re.compile(
    r"""^\s*import\s+['"](\.[^'"]+)['"]""", re.MULTILINE
)

# ESM: export ... from './module'
RE_ESM_EXPORT_FROM = re.compile(
    r"""^\s*export\s+.+\s+from\s+['"](\.[^'"]+)['"]""", re.MULTILINE
)

# Dynamic import: import('./module')
RE_DYNAMIC_IMPORT = re.compile(
    r"""import\s*\(\s*['"](\.[^'"]+)['"]\s*\)"""
)


class JavaScriptPlugin(LanguagePlugin):
    """JavaScript/TypeScript language plugin for amalgamation."""

    name = "javascript"
    extensions = [".js", ".mjs", ".cjs", ".jsx"]
    comment_prefix = "//"
    comment_block = ("/*", "*/")
    is_compiled = False

    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        """Extract require() and import statements from a JS file."""
        imports: list[ImportInfo] = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return imports

        seen: set[str] = set()

        # Parse all import patterns
        patterns = [
            (RE_ESM_IMPORT, "esm"),
            (RE_ESM_IMPORT_BARE, "esm_bare"),
            (RE_ESM_EXPORT_FROM, "esm_export"),
            (RE_REQUIRE, "require"),
            (RE_DYNAMIC_IMPORT, "dynamic"),
        ]

        for pattern, style in patterns:
            for match in pattern.finditer(content):
                module_path = match.group(1)
                if module_path in seen:
                    continue
                seen.add(module_path)

                # Find line number
                line_start = content[:match.start()].count("\n") + 1

                imports.append(ImportInfo(
                    raw_line=match.group(0).strip(),
                    import_name=module_path,
                    is_local=True,
                    line_number=line_start,
                ))

        return imports

    def resolve_import_path(
        self,
        import_info: ImportInfo,
        source_file: Path,
        search_paths: list[Path],
    ) -> Path | None:
        """Resolve a JS import path to an actual file."""
        module_path = import_info.import_name

        for search_dir in search_paths:
            resolved = self._try_resolve(search_dir, module_path)
            if resolved:
                return resolved

        return None

    def _try_resolve(self, base_dir: Path, module_path: str) -> Path | None:
        """Try to resolve a module path with Node.js conventions."""
        target = (base_dir / module_path).resolve()

        # 1. Exact file
        if target.is_file():
            return target

        # 2. With extensions
        for ext in (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"):
            candidate = target.with_suffix(ext)
            if candidate.is_file():
                return candidate

        # 3. Directory with index file
        if target.is_dir():
            for index_name in ("index.js", "index.mjs", "index.cjs", "index.ts"):
                index = target / index_name
                if index.is_file():
                    return index

        return None

    def extract_imports_from_line(
        self, line: str, source_file: Path,
    ) -> list[ImportInfo]:
        """Parse a single line for import statements."""
        results: list[ImportInfo] = []

        for pattern in [RE_ESM_IMPORT, RE_ESM_IMPORT_BARE, RE_REQUIRE]:
            match = pattern.search(line)
            if match:
                results.append(ImportInfo(
                    raw_line=line,
                    import_name=match.group(1),
                    is_local=True,
                ))
                break

        return results

    def get_compile_command(
        self,
        source: Path,
        output: Path | None,
        flags: list[str],
        compiler: str | None = None,
    ) -> list[str]:
        """JS is interpreted — use node --check for syntax check."""
        rt = compiler or find_runtime("javascript") or "node"
        return [rt, "--check", str(source)]

    def get_run_command(
        self,
        executable: Path,
        args: list[str],
        runtime: str | None = None,
    ) -> list[str]:
        """Run with Node.js."""
        rt = runtime or find_runtime("javascript") or "node"
        return [rt, str(executable)] + args

    def wrap_section(self, content: str, file_path: Path) -> str:
        """
        Wrap a JS module in an IIFE for namespace isolation.

        This prevents variable leakage between amalgamated modules.
        """
        module_name = file_path.stem.replace("-", "_").replace(".", "_")
        return (
            f"// Module: {file_path.name}\n"
            f"var _mod_{module_name} = (function() {{\n"
            f"  var module = {{exports: {{}}}};\n"
            f"  var exports = module.exports;\n"
            f"\n"
            f"{content}\n"
            f"\n"
            f"  return module.exports;\n"
            f"}})();\n"
        )


# ── Self-register ────────────────────────────────────────────────────────────

LanguageRegistry.register(JavaScriptPlugin())
