"""
TypeScript language plugin — handles import resolution and amalgamation.

Extends JavaScript support with TypeScript-specific features:
- .ts, .tsx, .d.ts file extensions
- Type-only imports (import type { X } from './module')
- deno/ts-node/bun runtime detection
"""

from __future__ import annotations

import re
from pathlib import Path

from amalgamator.languages.base import LanguagePlugin, ImportInfo
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.utils.detection import find_runtime

# ── Import parsing patterns ──────────────────────────────────────────────────

# ESM: import X from './module'
RE_ESM_IMPORT = re.compile(
    r"""^\s*import\s+.+\s+from\s+['"](\.[^'"]+)['"]""", re.MULTILINE
)

# ESM: import type { X } from './module'
RE_TYPE_IMPORT = re.compile(
    r"""^\s*import\s+type\s+.+\s+from\s+['"](\.[^'"]+)['"]""", re.MULTILINE
)

# ESM: import './module' (side-effect)
RE_ESM_BARE = re.compile(
    r"""^\s*import\s+['"](\.[^'"]+)['"]""", re.MULTILINE
)

# ESM: export ... from './module'
RE_ESM_EXPORT = re.compile(
    r"""^\s*export\s+.+\s+from\s+['"](\.[^'"]+)['"]""", re.MULTILINE
)

# Dynamic: import('./module')
RE_DYNAMIC = re.compile(
    r"""import\s*\(\s*['"](\.[^'"]+)['"]\s*\)"""
)


class TypeScriptPlugin(LanguagePlugin):
    """TypeScript language plugin for amalgamation."""

    name = "typescript"
    extensions = [".ts", ".tsx"]
    comment_prefix = "//"
    comment_block = ("/*", "*/")
    is_compiled = False  # Interpreted via deno/ts-node/bun

    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        """Extract import statements from a TypeScript file."""
        imports: list[ImportInfo] = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return imports

        seen: set[str] = set()

        patterns = [
            RE_TYPE_IMPORT,
            RE_ESM_IMPORT,
            RE_ESM_BARE,
            RE_ESM_EXPORT,
            RE_DYNAMIC,
        ]

        for pattern in patterns:
            for match in pattern.finditer(content):
                module_path = match.group(1)
                if module_path in seen:
                    continue
                seen.add(module_path)

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
        """Resolve a TypeScript import to a file path."""
        module_path = import_info.import_name

        for search_dir in search_paths:
            resolved = self._try_resolve(search_dir, module_path)
            if resolved:
                return resolved

        return None

    def _try_resolve(self, base_dir: Path, module_path: str) -> Path | None:
        """Try to resolve with TypeScript conventions."""
        target = (base_dir / module_path).resolve()

        # 1. Exact file
        if target.is_file():
            return target

        # 2. TypeScript extensions first, then JS
        for ext in (".ts", ".tsx", ".d.ts", ".js", ".mjs", ".jsx"):
            candidate = target.with_suffix(ext)
            if candidate.is_file():
                return candidate

        # 3. Directory with index file
        if target.is_dir():
            for idx in ("index.ts", "index.tsx", "index.js"):
                index = target / idx
                if index.is_file():
                    return index

        return None

    def extract_imports_from_line(self, line: str, source_file: Path) -> list[ImportInfo]:
        """Parse a single line for import statements."""
        for pattern in [RE_TYPE_IMPORT, RE_ESM_IMPORT, RE_ESM_BARE]:
            match = pattern.search(line)
            if match:
                return [ImportInfo(raw_line=line, import_name=match.group(1), is_local=True)]
        return []

    def detect_entry_point(self, files: list[Path]) -> Path | None:
        """Auto-detect entry point: look for main.ts or index.ts."""
        for name in ("main.ts", "index.ts", "app.ts"):
            for f in files:
                if f.name == name:
                    return f
        return None

    def get_compile_command(self, source, output, flags, compiler=None) -> list[str]:
        """TypeScript — use deno check or tsc for type checking."""
        deno = find_runtime("typescript")
        if deno and "deno" in deno:
            return [deno, "check", str(source)]

        # Fallback to tsc if available
        import shutil
        tsc = shutil.which("tsc")
        if tsc:
            return [tsc, "--noEmit"] + flags + [str(source)]

        return ["deno", "check", str(source)]

    def get_run_command(self, executable, args, runtime=None) -> list[str]:
        """Run with deno, ts-node, or bun."""
        rt = runtime or find_runtime("typescript") or "deno"

        if "deno" in rt:
            return [rt, "run", "--allow-all", str(executable)] + args
        elif "bun" in rt:
            return [rt, "run", str(executable)] + args
        else:
            return [rt, str(executable)] + args


# ── Self-register ────────────────────────────────────────────────────────────

LanguageRegistry.register(TypeScriptPlugin())
