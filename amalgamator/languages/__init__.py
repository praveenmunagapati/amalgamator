"""Language plugins for parsing imports, amalgamating, compiling, and running source files."""

from amalgamator.languages.base import LanguagePlugin
from amalgamator.languages.registry import LanguageRegistry

__all__ = ["LanguagePlugin", "LanguageRegistry"]
