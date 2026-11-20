from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union


@dataclass(frozen=True)
class LanguageSpec:
    """Immutable specification descriptor for a supported programming language."""
    name: str
    extensions: Tuple[str, ...]
    manifest_names: Tuple[str, ...] = ()
    tool_names: Tuple[str, ...] = ()


class LanguageRegistry:
    """
    Registry for language backends, specifications, and extension mappings.
    Single source of truth for language metadata across the indexing subsystem.
    """

    _languages: Set[str] = set()
    _specs: Dict[str, LanguageSpec] = {}
    _extension_map: Dict[str, str] = {}
    _name_map: Dict[str, str] = {}
    _manifest_map: Dict[str, str] = {}

    @classmethod
    def register(cls,
                  language: str,
                  extensions: Optional[Sequence[str]] = None,
                  tool_names: Optional[Sequence[str]] = None,
                  manifest_names: Optional[Sequence[str]] = None,
                  spec: Optional[LanguageSpec] = None,
                  **kwargs) -> None:
        """Register a language with its file extensions, manifests, and tool names."""
        if spec is None:
            spec = LanguageSpec(
                name=language,
                extensions=tuple(extensions or ()),
                manifest_names=tuple(manifest_names or ()),
                tool_names=tuple(tool_names or ()),
            )

        cls._languages.add(language)
        cls._specs[language] = spec

        for ext in spec.extensions:
            cls._extension_map[ext] = language
        for name in spec.tool_names:
            cls._name_map[name] = language
        for manifest in spec.manifest_names:
            cls._manifest_map[manifest] = language
            cls._name_map[manifest] = language

    @classmethod
    def get_spec(cls, language: str) -> Optional[LanguageSpec]:
        """Get LanguageSpec by language name."""
        return cls._specs.get(language)

    @classmethod
    def list_extensions(cls) -> Set[str]:
        """List all registered file extensions."""
        return set(cls._extension_map.keys())

    @classmethod
    def get_manifest_for_language(cls, language: str) -> Optional[str]:
        """Return the primary package manifest filename for a language."""
        spec = cls._specs.get(language)
        if spec and spec.manifest_names:
            return spec.manifest_names[0]
        return None

    @classmethod
    def detect_language(cls, filepath: Union[str, Path]) -> Optional[str]:
        """Detect language from file extension or extension string."""
        p_str = str(filepath)
        ext = Path(p_str).suffix.lower()
        if ext:
            return cls._extension_map.get(ext)
        if p_str.startswith("."):
            return cls._extension_map.get(p_str.lower())
        return None

    @classmethod
    def detect_language_from_name(cls, name: str) -> Optional[str]:
        """Detect language from tool/project name (e.g., 'Cargo.toml' → 'rust')."""
        return cls._name_map.get(name) or cls._manifest_map.get(name)

    @classmethod
    def list_languages(cls) -> List[str]:
        """List all registered languages."""
        return sorted(list(cls._languages))

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._languages.clear()
        cls._specs.clear()
        cls._extension_map.clear()
        cls._name_map.clear()
        cls._manifest_map.clear()

    @classmethod
    def register_defaults(cls) -> None:
        """Register all built-in language specifications."""
        cls.clear()
        cls.register(
            "rust",
            extensions=(".rs",),
            manifest_names=("Cargo.toml",),
            tool_names=("Cargo.toml", "rust-analyzer"),
        )
        cls.register(
            "dart",
            extensions=(".dart",),
            manifest_names=("pubspec.yaml",),
            tool_names=("pubspec.yaml", "dart"),
        )
        cls.register(
            "python",
            extensions=(".py", ".pyi"),
            manifest_names=("requirements.txt", "pyproject.toml", "setup.py"),
            tool_names=("setup.py", "pyproject.toml", "requirements.txt"),
        )
        cls.register(
            "go",
            extensions=(".go",),
            manifest_names=("go.mod",),
            tool_names=("go.mod",),
        )
        cls.register(
            "typescript",
            extensions=(".ts", ".tsx"),
            manifest_names=("package.json", "tsconfig.json"),
            tool_names=("tsconfig.json", "package.json"),
        )
        cls.register(
            "javascript",
            extensions=(".js", ".jsx", ".mjs", ".cjs"),
            manifest_names=("package.json",),
            tool_names=("package.json",),
        )
        cls.register(
            "java",
            extensions=(".java",),
            manifest_names=("pom.xml", "build.gradle"),
            tool_names=("pom.xml", "build.gradle"),
        )
        cls.register(
            "cpp",
            extensions=(".cpp", ".cxx", ".cc", ".hpp", ".hxx"),
            manifest_names=("CMakeLists.txt",),
        )
        cls.register(
            "c",
            extensions=(".c", ".h"),
        )
        cls.register(
            "csharp",
            extensions=(".cs",),
            manifest_names=("*.csproj",),
            tool_names=("*.csproj",),
        )
        cls.register(
            "ruby",
            extensions=(".rb",),
            manifest_names=("Gemfile",),
            tool_names=("Gemfile",),
        )
        cls.register(
            "php",
            extensions=(".php",),
            manifest_names=("composer.json",),
            tool_names=("composer.json",),
        )
        cls.register(
            "html",
            extensions=(".html", ".htm"),
        )
        cls.register(
            "css",
            extensions=(".css", ".scss", ".less"),
        )
        cls.register(
            "bash",
            extensions=(".sh", ".bash"),
        )
        cls.register(
            "powershell",
            extensions=(".ps1", ".psm1"),
        )


# Register built-in languages
LanguageRegistry.register_defaults()
