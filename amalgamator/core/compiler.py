"""
Compiler dispatcher — invokes the correct compiler for each language.
"""

from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from amalgamator.utils.detection import find_compiler


@dataclass
class CompileResult:
    """Result of a compilation."""
    success: bool
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    output_path: Path | None = None


def compile_source(
    source_path: Path,
    language: str,
    output_path: Path | None = None,
    compiler: str | None = None,
    flags: list[str] | None = None,
    extra_sources: list[Path] | None = None,
) -> CompileResult:
    """
    Compile a source file using the appropriate compiler.

    Args:
        source_path: Path to the source file.
        language: Language identifier (c, cpp, java, rust, go).
        output_path: Desired output binary path.
        compiler: Override compiler command.
        flags: Additional compiler flags.
        extra_sources: Additional source files to compile together.

    Returns:
        CompileResult with success status and output details.
    """
    if flags is None:
        flags = []
    if extra_sources is None:
        extra_sources = []

    # Find compiler
    cc = compiler or find_compiler(language)
    if not cc:
        return CompileResult(
            success=False,
            command=[],
            stderr=f"No compiler found for language '{language}'. "
                   f"Please install one or specify with --compiler.",
            returncode=-1,
        )

    # Build the command
    cmd = _build_compile_command(
        cc, source_path, language, output_path, flags, extra_sources,
    )

    # Execute
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        return CompileResult(
            success=result.returncode == 0,
            command=cmd,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            output_path=output_path,
        )
    except subprocess.TimeoutExpired:
        return CompileResult(
            success=False,
            command=cmd,
            stderr="Compilation timed out after 5 minutes.",
            returncode=-1,
        )
    except FileNotFoundError:
        return CompileResult(
            success=False,
            command=cmd,
            stderr=f"Compiler '{cc}' not found. Is it installed and on PATH?",
            returncode=-1,
        )


def _build_compile_command(
    compiler: str,
    source: Path,
    language: str,
    output: Path | None,
    flags: list[str],
    extra_sources: list[Path],
) -> list[str]:
    """Build the compiler command line."""
    cmd: list[str] = [compiler]

    if language in ("c", "cpp"):
        if output:
            cmd.extend(["-o", str(output)])
        cmd.extend(flags)
        cmd.append(str(source))
        cmd.extend(str(s) for s in extra_sources)

    elif language == "java":
        if output:
            cmd.extend(["-d", str(output.parent)])
        cmd.extend(flags)
        cmd.append(str(source))
        cmd.extend(str(s) for s in extra_sources)

    elif language == "rust":
        if output:
            cmd.extend(["-o", str(output)])
        cmd.extend(flags)
        cmd.append(str(source))

    elif language == "go":
        cmd.append("build")
        if output:
            cmd.extend(["-o", str(output)])
        cmd.extend(flags)
        cmd.append(str(source))

    else:
        # Generic: just pass source and flags
        cmd.extend(flags)
        cmd.append(str(source))

    return cmd


def syntax_check(
    source_path: Path,
    language: str,
) -> CompileResult:
    """
    Perform a syntax check without full compilation (for interpreted languages).
    """
    cmd: list[str] = []

    if language == "python":
        runtime = shutil.which("python3") or shutil.which("python") or "python"
        cmd = [runtime, "-m", "py_compile", str(source_path)]

    elif language in ("javascript", "typescript"):
        node = shutil.which("node")
        if node:
            cmd = [node, "--check", str(source_path)]
        else:
            return CompileResult(
                success=False, command=[], stderr="Node.js not found.", returncode=-1,
            )
    else:
        return CompileResult(
            success=True, command=[], stdout="No syntax check available.", returncode=0,
        )

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return CompileResult(
            success=result.returncode == 0,
            command=cmd,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return CompileResult(
            success=False, command=cmd, stderr=str(e), returncode=-1,
        )
