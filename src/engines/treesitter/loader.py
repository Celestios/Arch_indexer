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


_languages: Dict[str, Any] = {}
_lock = threading.Lock()
_local = threading.local()


def detect_language(filepath: str | Path) -> Optional[str]:
    """Detect language from file path or extension via unified LanguageRegistry."""
    return LanguageRegistry.detect_language(filepath)


def is_available() -> bool:
    """Returns True if the tree-sitter core library is installed and available."""
    return tree_sitter is not None


def get_language(language: str) -> Optional[Any]:
    """Returns the tree_sitter.Language instance for a given language name."""
    if tree_sitter is None:
        return None
    lang_key = language.lower()
    with _lock:
        if lang_key in _languages:
            return _languages[lang_key]

        lang_obj = load_language(lang_key)
        if lang_obj:
            _languages[lang_key] = lang_obj
            return lang_obj
        return None


def get_parser(language: str) -> Optional[Any]:
    """Returns a thread-local cached tree_sitter.Parser initialized with the target language."""
    if tree_sitter is None:
        return None
    lang_key = language.lower()
    parsers = getattr(_local, "parsers", None)
    if parsers is None:
        parsers = {}
        _local.parsers = parsers

    if lang_key in parsers:
        return parsers[lang_key]

    lang_obj = get_language(lang_key)
    if not lang_obj:
        return None

    parser = tree_sitter.Parser(lang_obj)
    parsers[lang_key] = parser
    return parser


def load_language(lang: str) -> Optional[Any]:
    """Dynamically import tree-sitter language modules via LanguageRegistry."""
    try:
        spec = LanguageRegistry.get_spec(lang)
        if spec and spec.ts_module and spec.ts_factory:
            mod = importlib.import_module(spec.ts_module)
            factory = getattr(mod, spec.ts_factory)
            return tree_sitter.Language(factory())
    except Exception:
        return None
    return None
