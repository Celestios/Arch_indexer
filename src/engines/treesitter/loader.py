"""
Tree-sitter language loader and parser cache.
Manages Language and Parser instances for all supported programming languages.
"""
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
        """Internal loader attempting to import modern tree-sitter language modules."""
        try:
            if lang == "python":
                import tree_sitter_python
                return tree_sitter.Language(tree_sitter_python.language())
            elif lang == "rust":
                import tree_sitter_rust
                return tree_sitter.Language(tree_sitter_rust.language())
            elif lang in ("typescript", "ts"):
                import tree_sitter_typescript
                return tree_sitter.Language(tree_sitter_typescript.language_typescript())
            elif lang in ("tsx", "javascript", "js"):
                import tree_sitter_typescript
                return tree_sitter.Language(tree_sitter_typescript.language_tsx())
            elif lang == "go":
                import tree_sitter_go
                return tree_sitter.Language(tree_sitter_go.language())
            elif lang == "java":
                import tree_sitter_java
                return tree_sitter.Language(tree_sitter_java.language())
            elif lang == "c":
                import tree_sitter_c
                return tree_sitter.Language(tree_sitter_c.language())
            elif lang in ("cpp", "c++"):
                import tree_sitter_cpp
                return tree_sitter.Language(tree_sitter_cpp.language())
            elif lang in ("csharp", "c_sharp", "cs"):
                import tree_sitter_c_sharp
                return tree_sitter.Language(tree_sitter_c_sharp.language())
            elif lang == "ruby":
                import tree_sitter_ruby
                return tree_sitter.Language(tree_sitter_ruby.language())
            elif lang == "dart":
                try:
                    import tree_sitter_dart
                    return tree_sitter.Language(tree_sitter_dart.language())
                except ImportError:
                    return None
        except Exception as e:
            return None
        return None
