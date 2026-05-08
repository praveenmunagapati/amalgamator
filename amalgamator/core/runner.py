"""
Runner — executes compiled binaries or interpreted scripts.
"""

from __future__ import annotations

import subprocess
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from amalgamator.utils.detection import find_runtime


@dataclass
class RunResult:
    """Result of running a program."""
    success: bool
    command: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def run_program(
    path: Path,
    language: str,
    args: list[str] | None = None,
    runtime: str | None = None,
    timeout: int = 300,
    stream: bool = False,
) -> RunResult:
    """
    Execute a compiled binary or interpreted script.

    Args:
        path: Path to the executable or script.
        language: Language identifier.
        args: Arguments to pass to the program.
        runtime: Override runtime command.
        timeout: Execution timeout in seconds.
        stream: If True, stream output in real-time (returns empty stdout/stderr).

    Returns:
        RunResult with execution details.
    """
    if args is None:
        args = []

    cmd = _build_run_command(path, language, args, runtime)

    if not cmd:
        return RunResult(
            success=False,
            command=[],
            stderr=f"No runtime found for language '{language}'.",
            returncode=-1,
        )

    try:
        if stream:
            # Stream output in real-time
            process = subprocess.Popen(
                cmd,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            process.wait(timeout=timeout)
            return RunResult(
                success=process.returncode == 0,
                command=cmd,
                returncode=process.returncode,
            )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return RunResult(
                success=result.returncode == 0,
                command=cmd,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
            )

    except subprocess.TimeoutExpired:
        return RunResult(
            success=False,
            command=cmd,
            stderr=f"Program timed out after {timeout} seconds.",
            returncode=-1,
        )
    except FileNotFoundError:
        return RunResult(
            success=False,
            command=cmd,
            stderr=f"Runtime '{cmd[0]}' not found. Is it installed and on PATH?",
            returncode=-1,
        )
    except PermissionError:
        return RunResult(
            success=False,
            command=cmd,
            stderr=f"Permission denied when trying to execute '{path}'.",
            returncode=-1,
        )


def _build_run_command(
    path: Path,
    language: str,
    args: list[str],
    runtime: str | None,
) -> list[str]:
    """Build the execution command."""
    compiled_languages = {"c", "cpp", "rust"}

    if language in compiled_languages:
        # Run the compiled binary directly
        cmd = [str(path)] + args
        return cmd

    if language == "python":
        rt = runtime or find_runtime("python") or "python"
        return [rt, str(path)] + args

    if language in ("javascript", "typescript"):
        rt = runtime or find_runtime("javascript") or "node"
        return [rt, str(path)] + args

    if language == "java":
        rt = runtime or find_runtime("java") or "java"
        # For java, the path should be the class name (without .class)
        class_name = path.stem
        return [rt, "-cp", str(path.parent), class_name] + args

    if language == "go":
        rt = runtime or find_runtime("go") or "go"
        return [rt, "run", str(path)] + args

    # Fallback: try to run directly
    return [str(path)] + args
