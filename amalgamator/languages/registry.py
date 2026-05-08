"""
Language plugin registry — auto-discovers and manages language plugins.
"""

from __future__ import annotations

from amalgamator.languages.base import LanguagePlugin


class LanguageRegistry:
    """Registry of available language plugins."""

    _plugins: dict[str, LanguagePlugin] = {}

    @classmethod
    def register(cls, plugin: LanguagePlugin) -> None:
        """Register a language plugin."""
        cls._plugins[plugin.name] = plugin
        # Also register by extension aliases
        for ext in plugin.extensions:
            alias = ext.lstrip(".")
            if alias not in cls._plugins:
                cls._plugins[alias] = plugin

    @classmethod
    def get(cls, name: str) -> LanguagePlugin | None:
        """Get a plugin by language name or extension."""
        cls._ensure_loaded()
        return cls._plugins.get(name)

    @classmethod
    def get_by_extension(cls, extension: str) -> LanguagePlugin | None:
        """Get a plugin by file extension."""
        cls._ensure_loaded()
        ext = extension.lstrip(".")
        return cls._plugins.get(ext)

    @classmethod
    def available(cls) -> list[str]:
        """List available language names (not aliases)."""
        cls._ensure_loaded()
        seen = set()
        names = []
        for plugin in cls._plugins.values():
            if plugin.name not in seen:
                seen.add(plugin.name)
                names.append(plugin.name)
        return sorted(names)

    @classmethod
    def _ensure_loaded(cls) -> None:
        """Lazy-load all language plugins."""
        if cls._plugins:
            return
        # Import all language modules to trigger registration
        try:
            from amalgamator.languages import c_cpp  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.languages import python_lang  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.languages import javascript  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.languages import java  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.languages import rust  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.languages import go_lang  # noqa: F401
        except ImportError:
            pass
        try:
            from amalgamator.languages import typescript  # noqa: F401
        except ImportError:
            pass
