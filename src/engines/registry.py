from pathlib import Path
from typing import Dict, List, Optional, Set


class LanguageRegistry:
    """
    Registry for language backends and extension mappings.
    Replaces hardcoded extension->language mappings.
    """
    
    _languages: Set[str] = set()
    _extension_map: Dict[str, str] = {}
    _name_map: Dict[str, str] = {}  # tool name → language (e.g., "rust-analyzer" → "rust")
    
    @classmethod
    def register(cls, language: str,
                 extensions: Optional[List[str]] = None,
                 tool_names: Optional[List[str]] = None,
                 **kwargs) -> None:
        """Register a language with its file extensions and tool names."""
        cls._languages.add(language)
        for ext in (extensions or []):
            cls._extension_map[ext] = language
        for name in (tool_names or []):
            cls._name_map[name] = language
    
    @classmethod
    def detect_language(cls, filepath: str) -> Optional[str]:
        """Detect language from file extension or extension string."""
        ext = Path(filepath).suffix
        if ext:
            return cls._extension_map.get(ext)
        if filepath.startswith("."):
            return cls._extension_map.get(filepath)
        return None
    
    @classmethod
    def detect_language_from_name(cls, name: str) -> Optional[str]:
        """Detect language from tool/project name (e.g., 'Cargo.toml' → 'rust')."""
        return cls._name_map.get(name)
    
    @classmethod
    def list_languages(cls) -> List[str]:
        """List all registered languages."""
        return sorted(list(cls._languages))
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._languages.clear()
        cls._extension_map.clear()
        cls._name_map.clear()
    @classmethod
    def register_defaults(cls) -> None:
        """Register all built-in languages."""
        cls.clear()
        cls.register(
            "rust",
            extensions=[".rs"],
            tool_names=["Cargo.toml", "rust-analyzer"]
        )
        cls.register(
            "dart",
            extensions=[".dart"],
            tool_names=["pubspec.yaml", "dart"]
        )
        cls.register(
            "python",
            extensions=[".py"],
            tool_names=["setup.py", "pyproject.toml", "requirements.txt"]
        )
        cls.register(
            "go",
            extensions=[".go"],
            tool_names=["go.mod"]
        )
        cls.register(
            "typescript",
            extensions=[".ts", ".tsx"],
            tool_names=["tsconfig.json", "package.json"]
        )
        cls.register(
            "javascript",
            extensions=[".js", ".jsx"],
            tool_names=["package.json"]
        )
        cls.register(
            "java",
            extensions=[".java"],
            tool_names=["pom.xml", "build.gradle"]
        )
        cls.register(
            "cpp",
            extensions=[".cpp", ".cxx", ".cc", ".hpp", ".hxx"]
        )
        cls.register(
            "c",
            extensions=[".c"]
        )
        cls.register(
            "csharp",
            extensions=[".cs"],
            tool_names=["*.csproj"]
        )
        cls.register(
            "ruby",
            extensions=[".rb"],
            tool_names=["Gemfile"]
        )
        cls.register(
            "php",
            extensions=[".php"],
            tool_names=["composer.json"]
        )
        cls.register(
            "html",
            extensions=[".html", ".htm"]
        )
        cls.register(
            "css",
            extensions=[".css", ".scss", ".less"]
        )
        cls.register(
            "bash",
            extensions=[".sh", ".bash"]
        )
        cls.register(
            "powershell",
            extensions=[".ps1", ".psm1"]
        )


# Register built-in languages
LanguageRegistry.register_defaults()

