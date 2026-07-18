from pathlib import Path
from typing import Dict, List, Optional, Type


class LanguageRegistry:
    """
    Registry for language backends. New languages added by registration.
    Replaces hardcoded extension→language mappings in helpers.py, compiler.py, scip_wrapper.py.
    """
    
    _backends: Dict[str, Type] = {}
    _extension_map: Dict[str, str] = {}
    _name_map: Dict[str, str] = {}  # tool name → language (e.g., "rust-analyzer" → "rust")
    
    @classmethod
    def register(cls, language: str, backend: Type = None, 
                 extensions: List[str] = None, tool_names: List[str] = None) -> None:
        """Register a language backend with its file extensions and tool names."""
        if backend is not None:
            cls._backends[language] = backend
        for ext in (extensions or []):
            cls._extension_map[ext] = language
        for name in (tool_names or []):
            cls._name_map[name] = language
    
    @classmethod
    def get_backend(cls, language: str) -> Optional[Type]:
        """Get the backend class for a language."""
        return cls._backends.get(language)
    
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
        return list(cls._backends.keys())
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._backends.clear()
        cls._extension_map.clear()
        cls._name_map.clear()


# Register built-in languages
LanguageRegistry.register(
    "rust",
    extensions=[".rs"],
    tool_names=["Cargo.toml", "rust-analyzer"]
)
LanguageRegistry.register(
    "dart",
    extensions=[".dart"],
    tool_names=["pubspec.yaml", "dart"]
)
LanguageRegistry.register(
    "python",
    extensions=[".py"],
    tool_names=["setup.py", "pyproject.toml", "requirements.txt"]
)
LanguageRegistry.register(
    "go",
    extensions=[".go"],
    tool_names=["go.mod"]
)
LanguageRegistry.register(
    "typescript",
    extensions=[".ts", ".tsx"],
    tool_names=["tsconfig.json", "package.json"]
)
LanguageRegistry.register(
    "javascript",
    extensions=[".js", ".jsx"],
    tool_names=["package.json"]
)
LanguageRegistry.register(
    "java",
    extensions=[".java"],
    tool_names=["pom.xml", "build.gradle"]
)
LanguageRegistry.register(
    "cpp",
    extensions=[".cpp", ".cxx", ".cc", ".hpp", ".hxx"]
)
LanguageRegistry.register(
    "c",
    extensions=[".c"]
)
LanguageRegistry.register(
    "csharp",
    extensions=[".cs"],
    tool_names=["*.csproj"]
)
LanguageRegistry.register(
    "ruby",
    extensions=[".rb"],
    tool_names=["Gemfile"]
)
LanguageRegistry.register(
    "php",
    extensions=[".php"],
    tool_names=["composer.json"]
)
LanguageRegistry.register(
    "html",
    extensions=[".html", ".htm"]
)
LanguageRegistry.register(
    "css",
    extensions=[".css", ".scss", ".less"]
)
LanguageRegistry.register(
    "bash",
    extensions=[".sh", ".bash"]
)
LanguageRegistry.register(
    "powershell",
    extensions=[".ps1", ".psm1"]
)
