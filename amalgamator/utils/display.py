"""
Rich console display helpers for beautiful terminal output.

Provides progress bars, syntax-highlighted previews, error panels,
dependency tree visualization, and summary tables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Force UTF-8 on Windows to support emoji in Rich output
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Attempt to set console mode to UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError):
        pass

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

if TYPE_CHECKING:
    from amalgamator.core.dependency_graph import DependencyGraph

# ── Shared console instance ─────────────────────────────────────────────────

console = Console()
error_console = Console(stderr=True)


# ── Branding ─────────────────────────────────────────────────────────────────

BANNER = r"""
[bold cyan]
   _                  _                        _             
  /_\  _ __ ___   __ _| | __ _  __ _ _ __ ___ | |_ ___  _ __ 
 //_\\| '_ ` _ \ / _` | |/ _` |/ _` | '_ ` _ \| __/ _ \| '__|
/  _  \ | | | | | (_| | | (_| | (_| | | | | | | || (_) | |   
\_/ \_/_| |_| |_|\__,_|_|\__, |\__,_|_| |_| |_|\__\___/|_|   
                         |___/                                
[/bold cyan]
[dim]Multi-language source amalgamation, compilation & execution[/dim]
"""


def print_banner() -> None:
    """Print the Amalgamator ASCII banner."""
    console.print(BANNER)


# ── Progress bars ────────────────────────────────────────────────────────────

def create_progress() -> Progress:
    """Create a styled progress bar for file processing."""
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40, style="cyan", complete_style="bold green"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )


# ── File scanning display ───────────────────────────────────────────────────

def print_scan_results(
    files: list[Path],
    language: str,
    base_path: Path,
) -> None:
    """Display scanned files in a rich table."""
    table = Table(
        title=f"📂 Scanned Files ({language.upper()})",
        title_style="bold cyan",
        border_style="dim",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("File", style="green")
    table.add_column("Size", style="yellow", justify="right")

    for i, f in enumerate(files, 1):
        rel = f.relative_to(base_path) if f.is_relative_to(base_path) else f
        size = f.stat().st_size
        size_str = _format_size(size)
        table.add_row(str(i), str(rel), size_str)

    console.print(table)
    console.print(f"\n  [bold]{len(files)}[/bold] files found\n", style="dim")


def _format_size(size_bytes: int) -> str:
    """Format bytes into a human-readable size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}" if unit == "B" else f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ── Dependency tree display ──────────────────────────────────────────────────

def print_dependency_tree(
    graph: dict[Path, list[Path]],
    entry_point: Path | None,
    base_path: Path,
) -> None:
    """Display the dependency graph as a Rich tree."""
    tree = Tree(
        "🔗 [bold cyan]Dependency Graph[/bold cyan]",
        guide_style="dim",
    )

    visited: set[Path] = set()

    def _add_node(parent: Tree, file: Path, depth: int = 0) -> None:
        if depth > 20:  # Guard against deep recursion
            parent.add("[dim]...[/dim]")
            return

        rel = file.relative_to(base_path) if file.is_relative_to(base_path) else file
        label = f"[green]{rel}[/green]"

        if file in visited:
            parent.add(f"{label} [dim](already shown)[/dim]")
            return

        visited.add(file)
        node = parent.add(label)

        deps = graph.get(file, [])
        for dep in deps:
            _add_node(node, dep, depth + 1)

    # Start from entry point if specified, otherwise show all roots
    if entry_point and entry_point in graph:
        _add_node(tree, entry_point)
    else:
        # Find root files (files not imported by anything else)
        all_deps: set[Path] = set()
        for deps in graph.values():
            all_deps.update(deps)
        roots = [f for f in graph if f not in all_deps]

        if not roots:
            roots = list(graph.keys())[:5]

        for root in sorted(roots):
            _add_node(tree, root)

    console.print(tree)
    console.print()


# ── Merge summary ────────────────────────────────────────────────────────────

def print_merge_summary(
    source_files: list[Path],
    output_file: Path,
    base_path: Path,
) -> None:
    """Display a summary table after amalgamation."""
    total_source_size = sum(f.stat().st_size for f in source_files)
    output_size = output_file.stat().st_size

    table = Table(
        title="✅ Amalgamation Complete",
        title_style="bold green",
        border_style="dim",
        padding=(0, 1),
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value", style="cyan")

    table.add_row("Files merged", str(len(source_files)))
    table.add_row("Source total size", _format_size(total_source_size))
    table.add_row("Output size", _format_size(output_size))
    table.add_row("Output file", str(output_file))

    console.print(table)
    console.print()


# ── Compilation display ──────────────────────────────────────────────────────

def print_compile_start(command: list[str]) -> None:
    """Display the compilation command being run."""
    cmd_str = " ".join(command)
    console.print(
        Panel(
            f"[bold]{cmd_str}[/bold]",
            title="🔨 [bold yellow]Compiling[/bold yellow]",
            border_style="yellow",
            padding=(0, 1),
        )
    )


def print_compile_success(output_path: Path | None = None) -> None:
    """Display compilation success message."""
    msg = "Compilation successful!"
    if output_path:
        msg += f"\n  Output: [cyan]{output_path}[/cyan]"
    console.print(f"\n  [bold green]✅ {msg}[/bold green]\n")


def print_compile_error(stderr: str, returncode: int) -> None:
    """Display compilation errors in a rich panel."""
    console.print(
        Panel(
            Syntax(stderr, "text", theme="monokai", word_wrap=True),
            title=f"❌ [bold red]Compilation Failed (exit code {returncode})[/bold red]",
            border_style="red",
            padding=(1, 2),
        )
    )


# ── Execution display ────────────────────────────────────────────────────────

def print_run_start(command: list[str]) -> None:
    """Display the execution command."""
    cmd_str = " ".join(command)
    console.print(
        Panel(
            f"[bold]{cmd_str}[/bold]",
            title="🚀 [bold green]Running[/bold green]",
            border_style="green",
            padding=(0, 1),
        )
    )


def print_run_output(stdout: str, stderr: str, returncode: int) -> None:
    """Display program output."""
    if stdout.strip():
        console.print(
            Panel(
                stdout.rstrip(),
                title="[bold]Program Output[/bold]",
                border_style="cyan",
                padding=(0, 1),
            )
        )

    if stderr.strip():
        console.print(
            Panel(
                Text(stderr.rstrip(), style="yellow"),
                title="[bold yellow]Stderr[/bold yellow]",
                border_style="yellow",
                padding=(0, 1),
            )
        )

    style = "green" if returncode == 0 else "red"
    icon = "✅" if returncode == 0 else "❌"
    console.print(f"\n  {icon} Process exited with code [bold {style}]{returncode}[/bold {style}]\n")


# ── Error display ────────────────────────────────────────────────────────────

def print_error(message: str, detail: str | None = None) -> None:
    """Display an error message in a red panel."""
    content = message
    if detail:
        content += f"\n\n[dim]{detail}[/dim]"

    error_console.print(
        Panel(
            content,
            title="❌ [bold red]Error[/bold red]",
            border_style="red",
            padding=(1, 2),
        )
    )


def print_warning(message: str) -> None:
    """Display a warning message."""
    console.print(f"  [bold yellow]⚠ Warning:[/bold yellow] {message}")


def print_info(message: str) -> None:
    """Display an info message."""
    console.print(f"  [bold cyan]ℹ[/bold cyan] {message}")


def print_success(message: str) -> None:
    """Display a success message."""
    console.print(f"  [bold green]✅[/bold green] {message}")


# ── Cycle detection display ──────────────────────────────────────────────────

def print_cycle_error(cycle: list[Path], base_path: Path) -> None:
    """Display a circular dependency error with the cycle path."""
    cycle_strs = []
    for f in cycle:
        rel = f.relative_to(base_path) if f.is_relative_to(base_path) else f
        cycle_strs.append(f"[yellow]{rel}[/yellow]")

    cycle_display = " → ".join(cycle_strs)

    error_console.print(
        Panel(
            f"Circular dependency detected:\n\n  {cycle_display}\n\n"
            "[dim]Break the cycle by removing or refactoring one of the imports.[/dim]",
            title="🔄 [bold red]Circular Dependency[/bold red]",
            border_style="red",
            padding=(1, 2),
        )
    )


# ── Config display ───────────────────────────────────────────────────────────

def print_config(config: dict) -> None:
    """Display the current configuration in a formatted panel."""
    import json

    formatted = json.dumps(config, indent=2, default=str)
    console.print(
        Panel(
            Syntax(formatted, "json", theme="monokai"),
            title="⚙️  [bold cyan]Configuration[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


# ── File preview ─────────────────────────────────────────────────────────────

def print_file_preview(
    file_path: Path,
    language: str = "text",
    max_lines: int = 30,
) -> None:
    """Display a syntax-highlighted preview of a file."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()

    if len(lines) > max_lines:
        preview = "\n".join(lines[:max_lines])
        preview += f"\n\n... ({len(lines) - max_lines} more lines)"
    else:
        preview = content

    console.print(
        Panel(
            Syntax(preview, language, theme="monokai", line_numbers=True),
            title=f"📄 [bold]{file_path.name}[/bold]",
            border_style="dim",
            padding=(0, 1),
        )
    )
