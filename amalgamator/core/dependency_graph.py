"""
Dependency graph — builds a DAG of file dependencies and performs topological sort.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Protocol


class ImportParser(Protocol):
    """Protocol for language-specific import parsers."""

    def extract_imports(self, file_path: Path) -> list[str]:
        """Extract import/include statements from a file."""
        ...

    def resolve_import_path(
        self, import_name: str, source_file: Path, search_paths: list[Path]
    ) -> Path | None:
        """Resolve an import name to an actual file path."""
        ...


class CycleError(Exception):
    """Raised when a circular dependency is detected."""

    def __init__(self, cycle: list[Path]) -> None:
        self.cycle = cycle
        cycle_str = " → ".join(str(p.name) for p in cycle)
        super().__init__(f"Circular dependency detected: {cycle_str}")


class DependencyGraph:
    """
    Directed acyclic graph (DAG) of file dependencies.

    Builds edges from import/include statements, detects cycles,
    and produces a topological ordering for amalgamation.
    """

    def __init__(self) -> None:
        self.graph: dict[Path, list[Path]] = {}
        self._resolved: list[Path] | None = None

    def build(
        self,
        files: list[Path],
        parser: ImportParser,
        search_paths: list[Path] | None = None,
    ) -> None:
        """
        Build the dependency graph from a list of files.

        Args:
            files: Source files to analyze.
            parser: Language-specific import parser.
            search_paths: Additional directories to search for imports.
        """
        if search_paths is None:
            search_paths = []

        file_set = set(files)

        for file_path in files:
            if file_path not in self.graph:
                self.graph[file_path] = []

            imports = parser.extract_imports(file_path)
            all_search = [file_path.parent] + search_paths

            for imp in imports:
                resolved = parser.resolve_import_path(imp, file_path, all_search)
                if resolved and resolved in file_set and resolved != file_path:
                    if resolved not in self.graph[file_path]:
                        self.graph[file_path].append(resolved)

                    # Ensure the dependency is also in the graph
                    if resolved not in self.graph:
                        self.graph[resolved] = []

        self._resolved = None  # Invalidate cache

    def detect_cycles(self) -> list[Path] | None:
        """
        Detect circular dependencies using DFS.

        Returns the cycle path if found, or None if the graph is acyclic.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[Path, int] = {node: WHITE for node in self.graph}
        parent: dict[Path, Path | None] = {node: None for node in self.graph}

        def _dfs(node: Path) -> list[Path] | None:
            color[node] = GRAY
            for neighbor in self.graph.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    # Found a cycle — reconstruct it
                    cycle = [neighbor, node]
                    current = node
                    while parent.get(current) and parent[current] != neighbor:
                        current = parent[current]  # type: ignore[assignment]
                        cycle.append(current)
                    cycle.reverse()
                    return cycle
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = _dfs(neighbor)
                    if result:
                        return result
            color[node] = BLACK
            return None

        for node in self.graph:
            if color[node] == WHITE:
                result = _dfs(node)
                if result:
                    return result

        return None

    def topological_sort(self) -> list[Path]:
        """
        Perform topological sort using Kahn's algorithm.

        Returns files in dependency order (dependencies first).
        Raises CycleError if a circular dependency is detected.
        """
        if self._resolved is not None:
            return self._resolved

        # Check for cycles first
        cycle = self.detect_cycles()
        if cycle:
            raise CycleError(cycle)

        # Kahn's algorithm
        in_degree: dict[Path, int] = {node: 0 for node in self.graph}
        for node in self.graph:
            for dep in self.graph[node]:
                if dep in in_degree:
                    in_degree[dep] = in_degree.get(dep, 0) + 1

        # Start with nodes that have no incoming edges (leaves / no dependents)
        queue: deque[Path] = deque()
        for node, degree in in_degree.items():
            if degree == 0:
                queue.append(node)

        result: list[Path] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for dep in self.graph.get(node, []):
                if dep in in_degree:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)

        if len(result) != len(self.graph):
            raise CycleError(list(self.graph.keys()))

        # Reverse so dependencies come first
        result.reverse()
        self._resolved = result
        return result

    def get_dependencies(self, file_path: Path) -> list[Path]:
        """Get direct dependencies of a file."""
        return self.graph.get(file_path, [])

    def get_all_dependencies(self, file_path: Path) -> set[Path]:
        """Get all transitive dependencies of a file (BFS)."""
        visited: set[Path] = set()
        queue: deque[Path] = deque([file_path])

        while queue:
            current = queue.popleft()
            for dep in self.graph.get(current, []):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)

        return visited

    @property
    def node_count(self) -> int:
        return len(self.graph)

    @property
    def edge_count(self) -> int:
        return sum(len(deps) for deps in self.graph.values())
