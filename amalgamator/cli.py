"""
Amalgamator CLI — the main command-line interface.

Usage:
    amalgamate scan   <path>              Scan & show dependency tree
    amalgamate merge  <path> -o <output>  Merge files into single file
    amalgamate build  <path> -o <output>  Merge + compile
    amalgamate run    <path>              Merge + compile + run
    amalgamate data   <path> -o <output>  Merge data files (JSON/XML/YAML/TOML)
    amalgamate config init                Create amalgamator.toml template
    amalgamate config show                Show current config
    amalgamate info                       Show available tools & languages
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import click
from rich.table import Table

from amalgamator import __version__
from amalgamator.utils.display import (
    console,
    print_banner,
    print_scan_results,
    print_dependency_tree,
    print_merge_summary,
    print_compile_start,
    print_compile_success,
    print_compile_error,
    print_run_start,
    print_run_output,
    print_error,
    print_warning,
    print_info,
    print_success,
    print_cycle_error,
    print_config,
)
from amalgamator.utils.detection import (
    detect_language_from_files,
    detect_available_tools,
    SOURCE_LANGUAGES,
)
from amalgamator.core.scanner import scan_directory
from amalgamator.core.dependency_graph import DependencyGraph, CycleError
from amalgamator.core.amalgamator import MergeEngine
from amalgamator.core.compiler import compile_source, syntax_check
from amalgamator.core.runner import run_program
from amalgamator.core.config import load_config, create_config
from amalgamator.languages.registry import LanguageRegistry
from amalgamator.data.registry import DataRegistry


# ── Shared options ───────────────────────────────────────────────────────────

def _common_options(f):
    """Shared CLI options for source commands."""
    f = click.option("--lang", "-l", default=None, help="Force language (auto-detect by default)")(f)
    f = click.option("--entry", "-e", default=None, help="Entry point / main file")(f)
    f = click.option("--compiler", "-c", default=None, help="Override compiler path")(f)
    f = click.option("--flags", "-f", default=None, help="Extra compiler flags (comma-separated)")(f)
    f = click.option("--verbose", "-v", is_flag=True, help="Verbose output")(f)
    f = click.option("--dry-run", is_flag=True, help="Show what would happen without executing")(f)
    return f


# ── Main group ───────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="amalgamate")
@click.pass_context
def main(ctx):
    """🔧 Amalgamator — Multi-language source file amalgamation, compilation & execution."""
    if ctx.invoked_subcommand is None:
        print_banner()
        click.echo(ctx.get_help())


# ── scan ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@_common_options
def scan(path, lang, entry, compiler, flags, verbose, dry_run):
    """📂 Scan files and display the dependency tree."""
    path = Path(path).resolve()

    # Load config
    config = load_config(path if path.is_dir() else path.parent)
    language = lang or config.language

    # Scan files
    try:
        file_set = scan_directory(
            path,
            language=language,
            exclude_patterns=config.exclude_patterns,
        )
    except FileNotFoundError as e:
        print_error(str(e))
        sys.exit(1)

    if not file_set.files:
        print_warning("No source files found.")
        sys.exit(0)

    # Detect language if not specified
    if not language:
        language = detect_language_from_files(file_set.files)
        if not language:
            print_error("Could not detect language. Use --lang to specify.")
            sys.exit(1)

    print_scan_results(file_set.files, language, file_set.base_path)

    # Build dependency graph
    plugin = LanguageRegistry.get(language)
    if not plugin:
        print_warning(f"No plugin for language '{language}'. Showing files without dependencies.")
        return

    graph = DependencyGraph()
    search_paths = [file_set.base_path]
    graph.build(file_set.files, plugin, search_paths)

    entry_path = _resolve_entry(entry, file_set.base_path) if entry else None
    print_dependency_tree(graph.graph, entry_path, file_set.base_path)

    print_info(f"Nodes: {graph.node_count}, Edges: {graph.edge_count}")

    # Check for cycles
    cycle = graph.detect_cycles()
    if cycle:
        print_cycle_error(cycle, file_set.base_path)


# ── merge ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", required=True, help="Output file path")
@_common_options
def merge(path, output, lang, entry, compiler, flags, verbose, dry_run):
    """📦 Merge source files into a single amalgamated file."""
    path = Path(path).resolve()
    output_path = Path(output).resolve()

    config = load_config(path if path.is_dir() else path.parent)
    language = lang or config.language

    # Scan
    file_set = scan_directory(path, language=language, exclude_patterns=config.exclude_patterns)
    if not file_set.files:
        print_error("No source files found.")
        sys.exit(1)

    if not language:
        language = detect_language_from_files(file_set.files)
    if not language:
        print_error("Could not detect language. Use --lang to specify.")
        sys.exit(1)

    plugin = LanguageRegistry.get(language)
    if not plugin:
        print_error(f"No plugin for language '{language}'.")
        sys.exit(1)

    # Build dependency graph & sort
    graph = DependencyGraph()
    graph.build(file_set.files, plugin, [file_set.base_path])

    try:
        ordered = graph.topological_sort()
    except CycleError as e:
        print_cycle_error(e.cycle, file_set.base_path)
        sys.exit(1)

    if verbose:
        print_dependency_tree(graph.graph, None, file_set.base_path)

    if dry_run:
        print_info("Dry run — would merge the following files in order:")
        for i, f in enumerate(ordered, 1):
            rel = f.relative_to(file_set.base_path) if f.is_relative_to(file_set.base_path) else f
            console.print(f"  {i}. {rel}")
        return

    # Amalgamate
    engine = MergeEngine(
        language=language,
        comment_prefix=plugin.comment_prefix,
        comment_block=plugin.comment_block,
    )

    result = engine.amalgamate(ordered, output_path, file_set.base_path)
    print_merge_summary(result.source_files, result.output_path, file_set.base_path)


# ── build ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output binary path")
@_common_options
def build(path, output, lang, entry, compiler, flags, verbose, dry_run):
    """🔨 Merge source files, then compile."""
    path = Path(path).resolve()
    config = load_config(path if path.is_dir() else path.parent)
    language = lang or config.language

    # Scan & detect
    file_set = scan_directory(path, language=language, exclude_patterns=config.exclude_patterns)
    if not file_set.files:
        print_error("No source files found.")
        sys.exit(1)

    if not language:
        language = detect_language_from_files(file_set.files)
    if not language:
        print_error("Could not detect language. Use --lang to specify.")
        sys.exit(1)

    plugin = LanguageRegistry.get(language)
    if not plugin:
        print_error(f"No plugin for language '{language}'.")
        sys.exit(1)

    # Parse flags
    compile_flags = _parse_flags(flags) or config.compiler_flags
    cc = compiler or config.compiler_command

    # Build dependency graph & sort
    graph = DependencyGraph()
    graph.build(file_set.files, plugin, [file_set.base_path])

    try:
        ordered = graph.topological_sort()
    except CycleError as e:
        print_cycle_error(e.cycle, file_set.base_path)
        sys.exit(1)

    # Determine output paths
    merged_ext = plugin.get_default_output_extension()
    merged_path = file_set.base_path / f"amalgamated{merged_ext}"

    if output:
        binary_path = Path(output).resolve()
    elif config.output_compiled:
        binary_path = Path(config.output_compiled).resolve()
    else:
        binary_path = file_set.base_path / "build" / (config.name or "output")

    if dry_run:
        print_info(f"Would merge {len(ordered)} files into {merged_path}")
        print_info(f"Would compile to {binary_path}")
        return

    # Step 1: Merge
    engine = MergeEngine(
        language=language,
        comment_prefix=plugin.comment_prefix,
        comment_block=plugin.comment_block,
    )
    merge_result = engine.amalgamate(ordered, merged_path, file_set.base_path)
    print_merge_summary(merge_result.source_files, merge_result.output_path, file_set.base_path)

    # Step 2: Compile
    if plugin.is_compiled:
        cmd = plugin.get_compile_command(merged_path, binary_path, compile_flags, cc)
        print_compile_start(cmd)

        compile_result = compile_source(
            merged_path, language, binary_path, cc, compile_flags,
        )

        if compile_result.success:
            print_compile_success(binary_path)
        else:
            print_compile_error(compile_result.stderr, compile_result.returncode)
            sys.exit(1)
    else:
        # Interpreted — just syntax check
        check = syntax_check(merged_path, language)
        if check.success:
            print_success(f"Syntax check passed for {merged_path.name}")
        else:
            print_compile_error(check.stderr, check.returncode)
            sys.exit(1)


# ── run ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output binary path")
@click.option("--args", "run_args", default=None, help="Arguments to pass to the program")
@_common_options
def run(path, output, run_args, lang, entry, compiler, flags, verbose, dry_run):
    """🚀 Merge, compile, and run in one step."""
    path = Path(path).resolve()
    config = load_config(path if path.is_dir() else path.parent)
    language = lang or config.language

    # Scan & detect
    file_set = scan_directory(path, language=language, exclude_patterns=config.exclude_patterns)
    if not file_set.files:
        print_error("No source files found.")
        sys.exit(1)

    if not language:
        language = detect_language_from_files(file_set.files)
    if not language:
        print_error("Could not detect language. Use --lang to specify.")
        sys.exit(1)

    plugin = LanguageRegistry.get(language)
    if not plugin:
        print_error(f"No plugin for language '{language}'.")
        sys.exit(1)

    compile_flags = _parse_flags(flags) or config.compiler_flags
    cc = compiler or config.compiler_command
    prog_args = run_args.split() if run_args else []

    # Build dependency graph & sort
    graph = DependencyGraph()
    graph.build(file_set.files, plugin, [file_set.base_path])

    try:
        ordered = graph.topological_sort()
    except CycleError as e:
        print_cycle_error(e.cycle, file_set.base_path)
        sys.exit(1)

    # Merge
    merged_ext = plugin.get_default_output_extension()
    merged_path = file_set.base_path / f"amalgamated{merged_ext}"

    engine = MergeEngine(
        language=language,
        comment_prefix=plugin.comment_prefix,
        comment_block=plugin.comment_block,
    )
    merge_result = engine.amalgamate(ordered, merged_path, file_set.base_path)
    print_merge_summary(merge_result.source_files, merge_result.output_path, file_set.base_path)

    # Compile (if needed)
    if plugin.is_compiled:
        if output:
            binary_path = Path(output).resolve()
        else:
            binary_path = file_set.base_path / "build" / (config.name or "output")

        binary_path.parent.mkdir(parents=True, exist_ok=True)
        compile_result = compile_source(merged_path, language, binary_path, cc, compile_flags)
        print_compile_start(compile_result.command)

        if compile_result.success:
            print_compile_success(binary_path)
        else:
            print_compile_error(compile_result.stderr, compile_result.returncode)
            sys.exit(1)

        # Run compiled binary
        run_cmd = plugin.get_run_command(binary_path, prog_args)
        print_run_start(run_cmd)
        run_result = run_program(binary_path, language, prog_args)
    else:
        # Interpreted — syntax check then run
        check = syntax_check(merged_path, language)
        if not check.success:
            print_compile_error(check.stderr, check.returncode)
            sys.exit(1)
        print_success("Syntax check passed")

        run_cmd = plugin.get_run_command(merged_path, prog_args)
        print_run_start(run_cmd)
        run_result = run_program(merged_path, language, prog_args)

    print_run_output(run_result.stdout, run_result.stderr, run_result.returncode)

    if not run_result.success:
        sys.exit(run_result.returncode or 1)


# ── data ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", required=True, help="Output file path")
@click.option("--format", "fmt", default=None, help="Data format (json, xml, yaml, toml)")
@click.option("--strategy", "-s", default="deep", type=click.Choice(["deep", "shallow", "concat"]))
@click.option("--verbose", "-v", is_flag=True)
def data(path, output, fmt, strategy, verbose):
    """📊 Merge data files (JSON, XML, YAML, TOML)."""
    path = Path(path).resolve()
    output_path = Path(output).resolve()

    # Determine format
    if not fmt:
        fmt = output_path.suffix.lstrip(".")
    if not fmt:
        print_error("Could not determine format. Use --format to specify.")
        sys.exit(1)

    merger = DataRegistry.get(fmt)
    if not merger:
        print_error(f"No merger for format '{fmt}'. Available: {', '.join(DataRegistry.available())}")
        sys.exit(1)

    # Collect data files
    if path.is_file():
        files = [path]
    else:
        exts = merger.extensions
        files = sorted(f for f in path.rglob("*") if f.suffix.lower() in exts)

    if not files:
        print_error(f"No {fmt.upper()} files found in {path}")
        sys.exit(1)

    if verbose:
        for f in files:
            print_info(f"Loading: {f}")

    # Merge
    result = merger.merge_files(files, strategy=strategy)

    if result.has_conflicts:
        for c in result.conflicts:
            print_warning(str(c))

    merger.dump(result.data, output_path)
    print_success(f"Merged {len(files)} files → {output_path}")


# ── config ───────────────────────────────────────────────────────────────────

@main.group()
def config():
    """⚙️  Manage project configuration."""
    pass


@config.command("init")
@click.argument("path", type=click.Path(), default=".")
def config_init(path):
    """Create a new amalgamator.toml config file."""
    path = Path(path).resolve()
    try:
        config_path = create_config(path)
        print_success(f"Created config: {config_path}")
    except FileExistsError as e:
        print_warning(str(e))


@config.command("show")
@click.argument("path", type=click.Path(exists=True), default=".")
def config_show(path):
    """Show current configuration."""
    path = Path(path).resolve()
    cfg = load_config(path)
    print_config(cfg.to_dict())


# ── info ─────────────────────────────────────────────────────────────────────

@main.command()
def info():
    """ℹ️  Show available languages, tools, and data formats."""
    print_banner()

    # Languages
    table = Table(title="🔤 Language Plugins", border_style="dim", title_style="bold cyan")
    table.add_column("Language", style="green")
    table.add_column("Extensions", style="yellow")
    table.add_column("Type", style="cyan")

    for lang_name in LanguageRegistry.available():
        plugin = LanguageRegistry.get(lang_name)
        if plugin:
            exts = ", ".join(plugin.extensions)
            ptype = "Compiled" if plugin.is_compiled else "Interpreted"
            table.add_row(plugin.name, exts, ptype)

    console.print(table)
    console.print()

    # Data formats
    table2 = Table(title="📊 Data Format Mergers", border_style="dim", title_style="bold cyan")
    table2.add_column("Format", style="green")
    table2.add_column("Extensions", style="yellow")

    for fmt_name in DataRegistry.available():
        merger = DataRegistry.get(fmt_name)
        if merger:
            exts = ", ".join(merger.extensions)
            table2.add_row(merger.name, exts)

    console.print(table2)
    console.print()

    # System tools
    tools = detect_available_tools()
    table3 = Table(title="🛠️  System Tools", border_style="dim", title_style="bold cyan")
    table3.add_column("Language", style="green")
    table3.add_column("Compiler", style="yellow")
    table3.add_column("Runtime", style="cyan")

    for lang, info_dict in tools.items():
        cc = info_dict["compiler"] or "[dim]not found[/dim]"
        rt = info_dict["runtime"] or "[dim]not found[/dim]"
        table3.add_row(lang, cc, rt)

    console.print(table3)
    console.print()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_entry(entry: str, base_path: Path) -> Path | None:
    """Resolve an entry point file path."""
    if not entry:
        return None
    p = Path(entry)
    if p.is_absolute():
        return p.resolve() if p.exists() else None
    candidate = base_path / p
    return candidate.resolve() if candidate.exists() else None


def _parse_flags(flags_str: str | None) -> list[str]:
    """Parse comma-separated compiler flags."""
    if not flags_str:
        return []
    return [f.strip() for f in flags_str.split(",") if f.strip()]


if __name__ == "__main__":
    main()
