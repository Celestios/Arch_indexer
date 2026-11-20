"""
Tree-sitter language loader and parser cache.
Manages Language and Parser instances for all supported programming languages.
"""
import importlib
from pathlib import Path
import threading
from typing import Dict, Optional, Tuple, Any

from engines.registry import LanguageRegistry

try:
    import tree_sitter
except ImportError:
    tree_sitter = None


class TreesitterLoader:
    """Manages compilation, loading and caching of tree-sitter parsers and languages."""

    _languages: Dict[str, Any] = {}
    _lock = threading.Lock()
    _local = threading.local()

    @classmethod
    def detect_language(cls, filepath: str | Path) -> Optional[str]:
        """Detect language from file path or extension via unified LanguageRegistry."""
        return LanguageRegistry.detect_language(filepath)

    @classmethod
    def is_available(cls) -> bool:
        """Returns True if the tree-sitter core library is installed and available."""
        return tree_sitter is not None

    @classmethod
    def get_language(cls, language: str) -> Optional[Any]:
        """Returns the tree_sitter.Language instance for a given language name."""
        if tree_sitter is None:
            return None
        lang_key = language.lower()
        with cls._lock:
            if lang_key in cls._languages:
                return cls._languages[lang_key]

            lang_obj = cls._load_language(lang_key)
            if lang_obj:
                cls._languages[lang_key] = lang_obj
                return lang_obj
            return None

    @classmethod
    def get_parser(cls, language: str) -> Optional[Any]:
        """Returns a thread-local cached tree_sitter.Parser initialized with the target language."""
        if tree_sitter is None:
            return None
        lang_key = language.lower()
        parsers = getattr(cls._local, "parsers", None)
        if parsers is None:
            parsers = {}
            cls._local.parsers = parsers

        if lang_key in parsers:
            return parsers[lang_key]

        lang_obj = cls.get_language(lang_key)
        if not lang_obj:
            return None

        parser = tree_sitter.Parser(lang_obj)
        parsers[lang_key] = parser
        return parser

    @classmethod
    def _load_language(cls, lang: str) -> Optional[tree_sitter.Language]:
        """Internal loader attempting to dynamically import tree-sitter language modules via LanguageRegistry."""
        try:
            spec = LanguageRegistry.get_spec(lang)
            if spec and spec.ts_module and spec.ts_factory:
                mod = importlib.import_module(spec.ts_module)
                factory = getattr(mod, spec.ts_factory)
                return tree_sitter.Language(factory())

            # Fallback for known aliases if registry spec was not found
            fallback_map = {
                "ts": ("tree_sitter_typescript", "language_typescript"),
                "js": ("tree_sitter_typescript", "language_tsx"),
                "tsx": ("tree_sitter_typescript", "language_tsx"),
                "c++": ("tree_sitter_cpp", "language"),
                "c_sharp": ("tree_sitter_c_sharp", "language"),
                "cs": ("tree_sitter_c_sharp", "language"),
            }
            if lang in fallback_map:
                mod_name, fn_name = fallback_map[lang]
                mod = importlib.import_module(mod_name)
                factory = getattr(mod, fn_name)
                return tree_sitter.Language(factory())
        except Exception:
            return None
        return None
