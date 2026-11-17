"""
Tree-sitter language loader and parser cache.
Manages Language and Parser instances for all supported programming languages.
"""
from pathlib import Path
from typing import Dict, Optional, Tuple, Any
import tree_sitter


class TreesitterLoader:
    """Manages compilation, loading and caching of tree-sitter parsers and languages."""

    _languages: Dict[str, tree_sitter.Language] = {}
    _parsers: Dict[str, tree_sitter.Parser] = {}

    # Map file extensions to normalized language names
    EXTENSION_MAP: Dict[str, str] = {
        ".py": "python",
        ".pyi": "python",
        ".rs": "rust",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".go": "go",
        ".java": "java",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".cs": "csharp",
        ".rb": "ruby",
    }

    @classmethod
    def detect_language(cls, filepath: str | Path) -> Optional[str]:
        """Detect language from file path or extension."""
        ext = Path(filepath).suffix.lower()
        return cls.EXTENSION_MAP.get(ext)

    @classmethod
    def get_language(cls, language: str) -> Optional[tree_sitter.Language]:
        """Returns the tree_sitter.Language instance for a given language name."""
        lang_key = language.lower()
        if lang_key in cls._languages:
            return cls._languages[lang_key]

        lang_obj = cls._load_language(lang_key)
        if lang_obj:
            cls._languages[lang_key] = lang_obj
            return lang_obj
        return None

    @classmethod
    def get_parser(cls, language: str) -> Optional[tree_sitter.Parser]:
        """Returns a cached tree_sitter.Parser initialized with the target language."""
        lang_key = language.lower()
        if lang_key in cls._parsers:
            return cls._parsers[lang_key]

        lang_obj = cls.get_language(lang_key)
        if not lang_obj:
            return None

        parser = tree_sitter.Parser(lang_obj)
        cls._parsers[lang_key] = parser
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
