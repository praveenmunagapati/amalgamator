"""
Lightweight C/C++ Preprocessor Evaluator.

This module provides a basic evaluator for preprocessor directives
(#define, #ifdef, #if defined, etc.) to determine if a line of code
is within an active block. This is critical for conditionally ignoring
#include directives that belong to inactive Hardware Abstraction Layers (HALs).
"""

from __future__ import annotations

import re

# Match #define A or #define A 1
RE_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z0-9_]+)(?:\s+(.*))?")
RE_UNDEF = re.compile(r"^\s*#\s*undef\s+([A-Za-z0-9_]+)")

# Match conditionals
RE_IFDEF = re.compile(r"^\s*#\s*ifdef\s+([A-Za-z0-9_]+)")
RE_IFNDEF = re.compile(r"^\s*#\s*ifndef\s+([A-Za-z0-9_]+)")
RE_IF_DEFINED = re.compile(r"^\s*#\s*if\s+defined\s*\(\s*([A-Za-z0-9_]+)\s*\)")
RE_IF_NOT_DEFINED = re.compile(r"^\s*#\s*if\s+!defined\s*\(\s*([A-Za-z0-9_]+)\s*\)")
RE_ELIF_DEFINED = re.compile(r"^\s*#\s*elif\s+defined\s*\(\s*([A-Za-z0-9_]+)\s*\)")

# Simple #if matching Marlin's ENABLED(X) -> assumes X is defined and == 1
RE_IF_ENABLED = re.compile(r"^\s*#\s*if\s+ENABLED\s*\(\s*([A-Za-z0-9_]+)\s*\)")
RE_IF_DISABLED = re.compile(r"^\s*#\s*if\s+DISABLED\s*\(\s*([A-Za-z0-9_]+)\s*\)")

# Catch-all for complex #if / #elif
RE_IF = re.compile(r"^\s*#\s*if\b(.*)")
RE_ELIF = re.compile(r"^\s*#\s*elif\b(.*)")
RE_ELSE = re.compile(r"^\s*#\s*else\b")
RE_ENDIF = re.compile(r"^\s*#\s*endif\b")


class CPreprocessor:
    """
    Evaluates basic C/C++ preprocessor directives line by line.

    Maintains a stack of active blocks. If a line is inside an inactive
    block, it can be safely ignored for dependency graph building.
    """

    def __init__(self, initial_defines: list[str] | None = None) -> None:
        self.defines: dict[str, str] = {}

        if initial_defines:
            for d in initial_defines:
                if "=" in d:
                    k, v = d.split("=", 1)
                    self.defines[k.strip()] = v.strip()
                else:
                    self.defines[d.strip()] = "1"

        # Stack tracks: (is_block_currently_active, has_any_block_in_chain_been_active)
        self.stack: list[tuple[bool, bool]] = []

    def is_defined(self, name: str) -> bool:
        """Check if a macro is defined."""
        return name in self.defines

    def is_active(self) -> bool:
        """Check if we are currently inside an active preprocessor block."""
        if not self.stack:
            return True
        return self.stack[-1][0]

    def process_line(self, line: str) -> bool:
        """
        Evaluate a line of code.

        Returns True if the line is an active non-directive line,
        False if it's inactive or a preprocessor directive.
        """
        stripped = line.strip()

        # Fast path
        if not stripped.startswith("#"):
            return self.is_active()

        # Handle #endif
        if RE_ENDIF.match(stripped):
            if self.stack:
                self.stack.pop()
            return False

        # Handle #else
        if RE_ELSE.match(stripped):
            if self.stack:
                current_active, chain_active = self.stack.pop()
                # Else is active only if no previous block in chain was active
                # AND the parent block (if any) is active.
                parent_active = self.stack[-1][0] if self.stack else True
                new_active = parent_active and not chain_active
                self.stack.append((new_active, chain_active or new_active))
            return False

        # Handle #ifdef
        match = RE_IFDEF.match(stripped)
        if match:
            self._push_if(self.is_defined(match.group(1)))
            return False

        # Handle #ifndef
        match = RE_IFNDEF.match(stripped)
        if match:
            self._push_if(not self.is_defined(match.group(1)))
            return False

        # Handle #if defined()
        match = RE_IF_DEFINED.match(stripped)
        if match:
            self._push_if(self.is_defined(match.group(1)))
            return False

        # Handle #if !defined()
        match = RE_IF_NOT_DEFINED.match(stripped)
        if match:
            self._push_if(not self.is_defined(match.group(1)))
            return False

        # Handle #if ENABLED() / DISABLED()
        match = RE_IF_ENABLED.match(stripped)
        if match:
            # Simplistic evaluation for Marlin
            self._push_if(self.is_defined(match.group(1)))
            return False

        match = RE_IF_DISABLED.match(stripped)
        if match:
            self._push_if(not self.is_defined(match.group(1)))
            return False

        # Handle complex #if (fallback to active to be safe)
        match = RE_IF.match(stripped)
        if match:
            # A full math evaluator goes here, but for lightweight we assume True
            # if we can't easily parse it, to avoid dropping valid dependencies.
            self._push_if(True)
            return False

        # Handle #elif defined()
        match = RE_ELIF_DEFINED.match(stripped)
        if match:
            self._handle_elif(self.is_defined(match.group(1)))
            return False

        # Handle complex #elif
        match = RE_ELIF.match(stripped)
        if match:
            self._handle_elif(True)
            return False

        # If we are active, process definitions
        if self.is_active():
            match = RE_DEFINE.match(stripped)
            if match:
                name = match.group(1)
                val = match.group(2) or "1"
                self.defines[name] = val
                return False

            match = RE_UNDEF.match(stripped)
            if match:
                self.defines.pop(match.group(1), None)
                return False

        # It's an unrecognized directive or a pragma inside an active block
        return self.is_active()

    def _push_if(self, condition: bool) -> None:
        """Push a new #if state onto the stack."""
        parent_active = self.stack[-1][0] if self.stack else True
        active = parent_active and condition
        self.stack.append((active, active))

    def _handle_elif(self, condition: bool) -> None:
        """Handle an #elif state transition."""
        if not self.stack:
            return
        current_active, chain_active = self.stack.pop()
        parent_active = self.stack[-1][0] if self.stack else True
        new_active = parent_active and not chain_active and condition
        self.stack.append((new_active, chain_active or new_active))
