"""
Amalgamator CLI — the main command-line interface.

Usage:
    amalgamate scan   <path>              Scan & show dependency tree
    amalgamate merge  <path> -o <output>  Merge files into single file
    amalgamate build  <path> -o <output>  Merge + compile
    amalgamate run    <path>              Merge + compile + run
    amalgamate watch  <path>              Watch for changes & auto-rebuild
    amalgamate data   <path> -o <output>  Merge data files (JSON/XML/YAML/TOML)
    amalgamate config init                Create amalgamator.toml template
    amalgamate config show                Show current config
    amalgamate info                       Show available tools & languages
"""

from __future__ import annotations

import sys
import time
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
)
from amalgamator.core.scanner import scan_directory
from amalgamator.core.dependency_graph import DependencyGraph, CycleError
from amalgamator.core.amalgamator import MergeEngine, reorder_with_entry_point
from amalgamator.core.compiler import compile_source, syntax_check
from amalgamator.core.runner import run_program
from amalgamator.core.config import load_config, create_config
from amalgamator.core.cache import BuildCache
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
    f = click.option("--no-cache", is_flag=True, help="Disable incremental build cache")(f)
    f = click.option("--ignore-cycles", is_flag=True, help="Ignore circular dependencies and force merge")(f)
    f = click.option("--profile", "-p", default=None, help="Hardware build profile to use from config")(f)
    return f


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


def _setup_pipeline(path, lang, entry, exclude_patterns=None, ignore_cycles=False, profile_name=None):
    """
    Common pipeline setup: scan files, detect language, get plugin,
    build dependency graph, resolve entry point.

    Returns (file_set, language, plugin, ordered_files, entry_point, graph, config) or exits on error.
    """
    path = Path(path).resolve()
    config = load_config(path if path.is_dir() else path.parent)
    language = lang or config.language

    # Scan
    excludes = (exclude_patterns or []) + (config.exclude_patterns or [])
    try:
        file_set = scan_directory(path, language=language, exclude_patterns=excludes)
    except FileNotFoundError as e:
        print_error(str(e))
        sys.exit(1)

    if not file_set.files:
        print_error("No source files found.")
        sys.exit(1)

    # Detect language
    if not language:
        language = detect_language_from_files(file_set.files)
    if not language:
        print_error("Could not detect language. Use --lang to specify.")
        sys.exit(1)

    # Get plugin
    plugin = LanguageRegistry.get(language)
    if not plugin:
        print_error(f"No plugin for language '{language}'.")
        sys.exit(1)

    # Apply Profile Settings
    search_paths = [file_set.base_path]
    if profile_name:
        if profile_name in config.profiles:
            prof = config.profiles[profile_name]
            if prof.compiler:
                config.compiler_command = prof.compiler
            config.compiler_flags.extend(prof.flags)
            config.compiler_flags.extend(f"-D{d}" for d in prof.defines)
            config.compiler_flags.extend(f"-I{i}" for i in prof.includes)
            plugin.defines = prof.defines
            if prof.objcopy:
                plugin.objcopy = prof.objcopy
            
            for inc in prof.includes:
                inc_path = (file_set.base_path / inc).resolve()
                if inc_path.is_dir() and inc_path not in search_paths:
                    search_paths.append(inc_path)
            
            print_info(f"Using build profile: {profile_name}")
        else:
            print_warning(f"Profile '{profile_name}' not found in config. Using defaults.")

    # Build dependency graph
    graph = DependencyGraph()
    graph.build(file_set.files, plugin, search_paths)

    try:
        ordered = graph.topological_sort(ignore_cycles=ignore_cycles)
    except CycleError as e:
        print_cycle_error(e.cycle, file_set.base_path)
        sys.exit(1)

    # Resolve entry point: user-specified > auto-detect
    if entry:
        entry_point = _resolve_entry(entry, file_set.base_path)
    else:
        entry_point = plugin.detect_entry_point(file_set.files)

    # Filter by reachability if we have an entry point
    if entry_point:
        reachable = graph.get_all_dependencies(entry_point)
        reachable.add(entry_point)
        ordered = [f for f in ordered if f in reachable]

    # Reorder so entry point is last
    if entry_point:
        ordered = reorder_with_entry_point(ordered, entry_point)
        print_info(f"Entry point: {entry_point.name}")

    return file_set, language, plugin, ordered, entry_point, graph, config


def _create_merge_engine(plugin, language, base_path, search_paths):
    """
    Create a MergeEngine wired up with the plugin's import stripping,
    section wrapping, and #line directive support.
    """
    def strip_fn(line, merged_files, source_file, search_paths):
        """Strip lines that import already-merged files."""
        if plugin.should_strip_import(line, merged_files, source_file, search_paths):
            # Replace with a comment showing the stripped import
            stripped = line.strip()
            return f"{plugin.comment_prefix} [amalgamator] stripped: {stripped}\n"
        return line

    return MergeEngine(
        language=language,
        comment_prefix=plugin.comment_prefix,
        comment_block=plugin.comment_block,
        strip_imports_fn=strip_fn,
        wrap_section_fn=plugin.wrap_section,
        line_directive_fn=plugin.generate_line_directive,
        emit_line_directives=plugin.is_compiled,  # Only for compiled languages
    )


# ── Main group ───────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="amalgamate")
@click.pass_context
def main(ctx):
    """Amalgamator — Multi-language source file amalgamation, compilation & execution."""
    if ctx.invoked_subcommand is None:
        print_banner()
        click.echo(ctx.get_help())


# ── scan ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@_common_options
def scan(path, lang, entry, compiler, flags, verbose, dry_run, no_cache, ignore_cycles, profile):
    """Scan files and display the dependency tree."""
    file_set, language, plugin, ordered, entry_point, graph, config = _setup_pipeline(
        path, lang, entry, ignore_cycles=ignore_cycles, profile_name=profile
    )

    print_scan_results(file_set.files, language, file_set.base_path)
    print_dependency_tree(graph.graph, entry_point, file_set.base_path)
    print_info(f"Nodes: {graph.node_count}, Edges: {graph.edge_count}")

    if entry_point:
        print_success(f"Entry point detected: {entry_point.name}")
    else:
        print_warning("No entry point detected. Use --entry to specify.")

    # Check for cycles
    cycle = graph.detect_cycles()
    if cycle:
        print_cycle_error(cycle, file_set.base_path)


# ── merge ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", required=True, help="Output file path")
@_common_options
def merge(path, output, lang, entry, compiler, flags, verbose, dry_run, no_cache, ignore_cycles, profile):
    """Merge source files into a single amalgamated file."""
    output_path = Path(output).resolve()
    file_set, language, plugin, ordered, entry_point, graph, config = _setup_pipeline(
        path, lang, entry, ignore_cycles=ignore_cycles, profile_name=profile
    )

    # Check cache
    if not no_cache:
        cache = BuildCache(file_set.base_path)
        if not cache.has_changed(file_set.files):
            print_success("No changes detected (cached). Use --no-cache to force rebuild.")
            return

    if verbose:
        print_dependency_tree(graph.graph, entry_point, file_set.base_path)

    if dry_run:
        print_info("Dry run — would merge the following files in order:")
        for i, f in enumerate(ordered, 1):
            rel = f.relative_to(file_set.base_path) if f.is_relative_to(file_set.base_path) else f
            marker = " (entry point)" if f == entry_point else ""
            console.print(f"  {i}. {rel}{marker}")
        return

    # Amalgamate with import stripping & #line directives
    engine = _create_merge_engine(plugin, language, file_set.base_path)
    result = engine.amalgamate(ordered, output_path, file_set.base_path)
    print_merge_summary(result.source_files, result.output_path, file_set.base_path)

    # Update cache
    if not no_cache:
        cache = BuildCache(file_set.base_path)
        cache.update(file_set.files, output_path)


# ── build ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output binary path")
@_common_options
def build(path, output, lang, entry, compiler, flags, verbose, dry_run, no_cache, ignore_cycles, profile):
    """Merge source files, then compile."""
    file_set, language, plugin, ordered, entry_point, graph, config = _setup_pipeline(
        path, lang, entry, ignore_cycles=ignore_cycles, profile_name=profile
    )

    compile_flags = _parse_flags(flags) or config.compiler_flags
    cc = compiler or config.compiler_command

    # Cache check
    if not no_cache:
        cache = BuildCache(file_set.base_path)
        if not cache.has_changed(file_set.files):
            print_success("No changes detected (cached). Use --no-cache to force rebuild.")
            return

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
        if plugin.is_compiled:
            cmd = plugin.get_compile_command(merged_path, binary_path, compile_flags, cc)
            print_info(f"Would compile with: {' '.join(cmd)}")
            for p_cmd in plugin.get_post_compile_commands(binary_path):
                print_info(f"Would run post-compile: {' '.join(p_cmd)}")
        else:
            print_info(f"Would compile to {binary_path}")
        return

    # Step 1: Merge
    engine = _create_merge_engine(plugin, language, file_set.base_path)
    merge_result = engine.amalgamate(ordered, merged_path, file_set.base_path)
    print_merge_summary(merge_result.source_files, merge_result.output_path, file_set.base_path)

    # Step 2: Compile
    if plugin.is_compiled:
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        compile_result = compile_source(merged_path, language, binary_path, cc, compile_flags)
        print_compile_start(compile_result.command)

        if compile_result.success:
            print_compile_success(binary_path)
            
            # Post-compile commands
            post_cmds = plugin.get_post_compile_commands(binary_path)
            for p_cmd in post_cmds:
                import subprocess
                print_info(f"Running post-compile: {' '.join(p_cmd)}")
                try:
                    res = subprocess.run(p_cmd, capture_output=True, text=True, timeout=60)
                    if res.returncode != 0:
                        print_compile_error(res.stderr, res.returncode)
                        sys.exit(1)
                except Exception as e:
                    print_error(f"Post-compile failed: {e}")
                    sys.exit(1)
        else:
            print_compile_error(compile_result.stderr, compile_result.returncode)
            sys.exit(1)
    else:
        check = syntax_check(merged_path, language)
        if check.success:
            print_success(f"Syntax check passed for {merged_path.name}")
        else:
            print_compile_error(check.stderr, check.returncode)
            sys.exit(1)

    # Update cache
    if not no_cache:
        cache = BuildCache(file_set.base_path)
        cache.update(file_set.files, merged_path)


# ── run ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output binary path")
@click.option("--args", "run_args", default=None, help="Arguments to pass to the program")
@_common_options
def run(path, output, run_args, lang, entry, compiler, flags, verbose, dry_run, no_cache, ignore_cycles, profile):
    """Merge, compile, and run in one step."""
    file_set, language, plugin, ordered, entry_point, graph, config = _setup_pipeline(
        path, lang, entry, ignore_cycles=ignore_cycles, profile_name=profile
    )

    compile_flags = _parse_flags(flags) or config.compiler_flags
    cc = compiler or config.compiler_command
    prog_args = run_args.split() if run_args else []

    # Merge
    merged_ext = plugin.get_default_output_extension()
    merged_path = file_set.base_path / f"amalgamated{merged_ext}"

    engine = _create_merge_engine(plugin, language, file_set.base_path)
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
            
            # Post-compile commands
            post_cmds = plugin.get_post_compile_commands(binary_path)
            for p_cmd in post_cmds:
                import subprocess
                print_info(f"Running post-compile: {' '.join(p_cmd)}")
                try:
                    res = subprocess.run(p_cmd, capture_output=True, text=True, timeout=60)
                    if res.returncode != 0:
                        print_compile_error(res.stderr, res.returncode)
                        sys.exit(1)
                except Exception as e:
                    print_error(f"Post-compile failed: {e}")
                    sys.exit(1)
        else:
            print_compile_error(compile_result.stderr, compile_result.returncode)
            sys.exit(1)

        run_cmd = plugin.get_run_command(binary_path, prog_args)
        print_run_start(run_cmd)
        run_result = run_program(binary_path, language, prog_args)
    else:
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


# ── watch ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--interval", default=1.0, help="Poll interval in seconds (default: 1.0)")
@click.option("--lang", "-l", default=None, help="Force language")
@click.option("--entry", "-e", default=None, help="Entry point file")
@click.option("--compiler", "-c", default=None, help="Override compiler")
@click.option("--flags", "-f", default=None, help="Compiler flags (comma-separated)")
def watch(path, output, interval, lang, entry, compiler, flags):
    """Watch for file changes and auto-rebuild."""
    path = Path(path).resolve()
    config = load_config(path if path.is_dir() else path.parent)
    language = lang or config.language

    print_banner()
    print_info(f"Watching {path} for changes (poll every {interval}s)...")
    print_info("Press Ctrl+C to stop.\n")

    cache = BuildCache(path if path.is_dir() else path.parent)
    build_count = 0

    try:
        while True:
            # Scan
            try:
                file_set = scan_directory(path, language=language,
                                          exclude_patterns=config.exclude_patterns)
            except FileNotFoundError:
                time.sleep(interval)
                continue

            if not file_set.files:
                time.sleep(interval)
                continue

            # Check for changes
            if not cache.has_changed(file_set.files):
                time.sleep(interval)
                continue

            # Something changed — rebuild
            build_count += 1
            detected_lang = language or detect_language_from_files(file_set.files)
            if not detected_lang:
                time.sleep(interval)
                continue

            plugin = LanguageRegistry.get(detected_lang)
            if not plugin:
                time.sleep(interval)
                continue

            console.rule(f"[bold cyan]Rebuild #{build_count}[/bold cyan]")

            # Build dependency graph
            graph = DependencyGraph()
            graph.build(file_set.files, plugin, [file_set.base_path])

            try:
                ordered = graph.topological_sort()
            except CycleError as e:
                print_cycle_error(e.cycle, file_set.base_path)
                cache.update(file_set.files)
                time.sleep(interval)
                continue

            # Entry point
            if entry:
                entry_point = _resolve_entry(entry, file_set.base_path)
            else:
                entry_point = plugin.detect_entry_point(file_set.files)

            if entry_point:
                ordered = reorder_with_entry_point(ordered, entry_point)

            # Merge
            merged_ext = plugin.get_default_output_extension()
            if output:
                merged_path = Path(output).resolve()
            else:
                merged_path = file_set.base_path / f"amalgamated{merged_ext}"

            try:
                engine = _create_merge_engine(plugin, detected_lang, file_set.base_path)
                result = engine.amalgamate(ordered, merged_path, file_set.base_path)
                print_merge_summary(result.source_files, result.output_path, file_set.base_path)

                # Try compile if compiled language
                if plugin.is_compiled:
                    compile_flags = _parse_flags(flags) or config.compiler_flags
                    cc = compiler or config.compiler_command
                    binary_path = file_set.base_path / "build" / (config.name or "output")
                    binary_path.parent.mkdir(parents=True, exist_ok=True)

                    compile_result = compile_source(merged_path, detected_lang, binary_path, cc, compile_flags)
                    if compile_result.success:
                        print_compile_success(binary_path)
                    else:
                        print_compile_error(compile_result.stderr, compile_result.returncode)
                else:
                    check = syntax_check(merged_path, detected_lang)
                    if check.success:
                        print_success("Syntax check passed")
                    else:
                        print_compile_error(check.stderr, check.returncode)

            except Exception as e:
                print_error(f"Build failed: {e}")

            cache.update(file_set.files, merged_path)
            time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\n  [bold yellow]Watch stopped.[/bold yellow]")


# ── data ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", required=True, help="Output file path")
@click.option("--format", "fmt", default=None, help="Data format (json, xml, yaml, toml)")
@click.option("--strategy", "-s", default="deep", type=click.Choice(["deep", "shallow", "concat"]))
@click.option("--verbose", "-v", is_flag=True)
def data(path, output, fmt, strategy, verbose):
    """Merge data files (JSON, XML, YAML, TOML)."""
    path = Path(path).resolve()
    output_path = Path(output).resolve()

    if not fmt:
        fmt = output_path.suffix.lstrip(".")
    if not fmt:
        print_error("Could not determine format. Use --format to specify.")
        sys.exit(1)

    merger = DataRegistry.get(fmt)
    if not merger:
        print_error(f"No merger for format '{fmt}'. Available: {', '.join(DataRegistry.available())}")
        sys.exit(1)

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

    # Error recovery: skip files that fail to parse
    valid_files: list[Path] = []
    for f in files:
        try:
            merger.load(f)  # Test load
            valid_files.append(f)
        except Exception as e:
            print_warning(f"Skipping {f.name}: {e}")

    if not valid_files:
        print_error("No valid data files could be parsed.")
        sys.exit(1)

    result = merger.merge_files(valid_files, strategy=strategy)

    if result.has_conflicts:
        for c in result.conflicts:
            print_warning(str(c))

    merger.dump(result.data, output_path)
    print_success(f"Merged {len(valid_files)} files -> {output_path}")


# ── config ───────────────────────────────────────────────────────────────────

@main.group()
def config():
    """Manage project configuration."""
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
    """Show available languages, tools, and data formats."""
    print_banner()

    # Languages
    table = Table(title="Language Plugins", border_style="dim", title_style="bold cyan")
    table.add_column("Language", style="green")
    table.add_column("Extensions", style="yellow")
    table.add_column("Type", style="cyan")
    table.add_column("Entry Detect", style="magenta")

    for lang_name in LanguageRegistry.available():
        plugin = LanguageRegistry.get(lang_name)
        if plugin:
            exts = ", ".join(plugin.extensions)
            ptype = "Compiled" if plugin.is_compiled else "Interpreted"
            has_entry = "Yes" if plugin.detect_entry_point([]) is not None or hasattr(plugin.detect_entry_point, '__func__') and plugin.detect_entry_point.__func__ is not LanguagePlugin.detect_entry_point else "No"
            # Simpler check: does the class override detect_entry_point?
            has_entry = "Yes" if type(plugin).detect_entry_point is not LanguagePlugin.detect_entry_point else "No"
            table.add_row(plugin.name, exts, ptype, has_entry)

    console.print(table)
    console.print()

    # Data formats
    table2 = Table(title="Data Format Mergers", border_style="dim", title_style="bold cyan")
    table2.add_column("Format", style="green")
    table2.add_column("Extensions", style="yellow")

    for fmt_name in DataRegistry.available():
        m = DataRegistry.get(fmt_name)
        if m:
            table2.add_row(m.name, ", ".join(m.extensions))

    console.print(table2)
    console.print()

    # System tools
    tools = detect_available_tools()
    table3 = Table(title="System Tools", border_style="dim", title_style="bold cyan")
    table3.add_column("Language", style="green")
    table3.add_column("Compiler", style="yellow")
    table3.add_column("Runtime", style="cyan")

    for lang_key, info_dict in tools.items():
        cc = info_dict["compiler"] or "[dim]not found[/dim]"
        rt = info_dict["runtime"] or "[dim]not found[/dim]"
        table3.add_row(lang_key, cc, rt)

    console.print(table3)
    console.print()


if __name__ == "__main__":
    main()
