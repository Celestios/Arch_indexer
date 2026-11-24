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
    ts_module: Optional[str] = None
    ts_factory: Optional[str] = None
    scip_binary: Optional[str] = None
    ast_node_kinds: Optional[Dict[str, str]] = None
    docstring_node_type: Optional[str] = None
    container_node_types: Tuple[str, ...] = ("Class", "Interface", "Struct", "Trait")
    impl_node_types: Tuple[str, ...] = ()
    di_call_patterns: Tuple[str, ...] = ()
    scip_command: Optional[Tuple[str, ...]] = None
    scip_prerequisites: Tuple[str, ...] = ()
    scip_index_subpath: Optional[str] = None
    is_client_lang: bool = False
    is_native_lang: bool = False


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
    def register(
        cls,
        language: str,
        extensions: Optional[Sequence[str]] = None,
        tool_names: Optional[Sequence[str]] = None,
        manifest_names: Optional[Sequence[str]] = None,
        spec: Optional[LanguageSpec] = None,
        ts_module: Optional[str] = None,
        ts_factory: Optional[str] = None,
        scip_binary: Optional[str] = None,
        ast_node_kinds: Optional[Dict[str, str]] = None,
        docstring_node_type: Optional[str] = None,
        container_node_types: Sequence[str] = ("Class", "Interface", "Struct", "Trait"),
        impl_node_types: Sequence[str] = (),
        di_call_patterns: Sequence[str] = (),
        scip_command: Optional[Sequence[str]] = None,
        scip_prerequisites: Sequence[str] = (),
        scip_index_subpath: Optional[str] = None,
        is_client_lang: bool = False,
        is_native_lang: bool = False,
    ) -> None:
        """Register a language with its file extensions, manifests, tool names, and backend bindings."""
        if spec is None:
            spec = LanguageSpec(
                name=language,
                extensions=tuple(extensions or ()),
                manifest_names=tuple(manifest_names or ()),
                tool_names=tuple(tool_names or ()),
                ts_module=ts_module,
                ts_factory=ts_factory,
                scip_binary=scip_binary,
                ast_node_kinds=ast_node_kinds,
                docstring_node_type=docstring_node_type,
                container_node_types=tuple(container_node_types),
                impl_node_types=tuple(impl_node_types),
                di_call_patterns=tuple(di_call_patterns),
                scip_command=tuple(scip_command) if scip_command is not None else None,
                scip_prerequisites=tuple(scip_prerequisites),
                scip_index_subpath=scip_index_subpath,
                is_client_lang=is_client_lang,
                is_native_lang=is_native_lang,
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
        """Get LanguageSpec by canonical language name."""
        return cls._specs.get(language.lower())

    @classmethod
    def list_extensions(cls) -> Set[str]:
        """List all registered file extensions."""
        return set(cls._extension_map.keys())

    @classmethod
    def get_client_extensions(cls) -> Set[str]:
        """List file extensions for client-tier languages (e.g. Dart, TS, JS, Python)."""
        exts: Set[str] = set()
        for spec in cls._specs.values():
            if spec.is_client_lang:
                exts.update(spec.extensions)
        return exts

    @classmethod
    def get_native_extensions(cls) -> Set[str]:
        """List file extensions for native-tier languages (e.g. Rust, C, C++)."""
        exts: Set[str] = set()
        for spec in cls._specs.values():
            if spec.is_native_lang:
                exts.update(spec.extensions)
        return exts

    @classmethod
    def get_all_specs(cls) -> List[LanguageSpec]:
        """Returns all registered LanguageSpec descriptors."""
        return list(cls._specs.values())

    @classmethod
    def get_manifest_for_language(cls, language: str) -> Optional[str]:
        """Return the primary package manifest filename for a language."""
        spec = cls.get_spec(language)
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
        """Detect language from tool/project name (e.g., 'Cargo.toml' -> 'rust')."""
        return cls._name_map.get(name) or cls._manifest_map.get(name)

    @classmethod
    def list_languages(cls) -> List[str]:
        """List all registered languages."""
        return sorted(cls._languages)

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
            tool_names=("Cargo.toml", "rust-analyzer", "rustup"),
            ts_module="tree_sitter_rust",
            ts_factory="language",
            scip_binary="rust-analyzer",
            impl_node_types=("impl_item",),
            container_node_types=("Class", "Interface", "Struct", "Trait", "Enum"),
            scip_command=("rust-analyzer", "scip", "."),
            is_native_lang=True,
            ast_node_kinds={
                "struct_item": "Struct",
                "enum_item": "Enum",
                "trait_item": "Trait",
                "function_item": "Function",
                "type_item": "TypeAlias",
            },
        )
        cls.register(
            "dart",
            extensions=(".dart",),
            manifest_names=("pubspec.yaml",),
            tool_names=("pubspec.yaml", "dart"),
            ts_module="tree_sitter_dart",
            ts_factory="language",
            scip_binary="dart",
            scip_command=("dart", "pub", "global", "run", "scip_dart", "."),
            di_call_patterns=("ref.watch", "ref.read", "context.read", "GetIt.instance.get"),
            container_node_types=("Class", "Interface", "Struct", "Trait", "Enum", "Extension", "Mixin"),
            is_client_lang=True,
            ast_node_kinds={
                "class_definition": "Class",
                "enum_declaration": "Enum",
                "extension_declaration": "Extension",
                "mixin_declaration": "Mixin",
                "function_signature": "Function",
                "method_signature": "Method",
                "constructor_signature": "Constructor",
                "getter_signature": "Getter",
                "setter_signature": "Setter",
            },
        )
        cls.register(
            "python",
            extensions=(".py", ".pyi"),
            manifest_names=("requirements.txt", "pyproject.toml", "setup.py"),
            tool_names=("setup.py", "pyproject.toml", "requirements.txt"),
            ts_module="tree_sitter_python",
            ts_factory="language",
            scip_binary="scip-python",
            docstring_node_type="expression_statement",
            container_node_types=("Class", "Function", "Method", "Constructor"),
            scip_command=("scip-python", "index"),
            is_client_lang=True,
            ast_node_kinds={
                "class_definition": "Class",
                "function_definition": "Function",
            },
        )
        cls.register(
            "go",
            extensions=(".go",),
            manifest_names=("go.mod",),
            tool_names=("go.mod",),
            ts_module="tree_sitter_go",
            ts_factory="language",
            scip_binary="scip-go",
            scip_command=("scip-go",),
            ast_node_kinds={
                "type_declaration": "Struct",
                "function_declaration": "Function",
                "method_declaration": "Method",
            },
        )
        cls.register(
            "typescript",
            extensions=(".ts", ".tsx"),
            manifest_names=("package.json", "tsconfig.json"),
            tool_names=("tsconfig.json", "package.json"),
            ts_module="tree_sitter_typescript",
            ts_factory="language_typescript",
            scip_binary="scip-typescript",
            scip_command=("scip-typescript", "index"),
            is_client_lang=True,
            ast_node_kinds={
                "class_declaration": "Class",
                "interface_declaration": "Interface",
                "type_alias_declaration": "TypeAlias",
                "enum_declaration": "Enum",
                "function_declaration": "Function",
                "method_definition": "Method",
            },
        )
        cls.register(
            "javascript",
            extensions=(".js", ".jsx", ".mjs", ".cjs"),
            manifest_names=("package.json",),
            tool_names=("package.json",),
            ts_module="tree_sitter_typescript",
            ts_factory="language_tsx",
            scip_binary="scip-typescript",
            scip_command=("scip-typescript", "index"),
            is_client_lang=True,
            ast_node_kinds={
                "class_declaration": "Class",
                "function_declaration": "Function",
                "method_definition": "Method",
            },
        )
        cls.register(
            "java",
            extensions=(".java",),
            manifest_names=("pom.xml", "build.gradle"),
            tool_names=("pom.xml", "build.gradle"),
            ts_module="tree_sitter_java",
            ts_factory="language",
            scip_binary="scip-java",
            scip_command=("scip-java", "index"),
            ast_node_kinds={
                "class_declaration": "Class",
                "interface_declaration": "Interface",
                "method_declaration": "Method",
            },
        )
        cls.register(
            "cpp",
            extensions=(".cpp", ".cxx", ".cc", ".hpp", ".hxx"),
            manifest_names=("CMakeLists.txt",),
            ts_module="tree_sitter_cpp",
            ts_factory="language",
            is_native_lang=True,
            ast_node_kinds={
                "class_specifier": "Class",
                "struct_specifier": "Struct",
                "function_definition": "Function",
            },
        )
        cls.register(
            "c",
            extensions=(".c", ".h"),
            ts_module="tree_sitter_c",
            ts_factory="language",
            is_native_lang=True,
            ast_node_kinds={
                "struct_specifier": "Struct",
                "function_definition": "Function",
            },
        )
        cls.register(
            "csharp",
            extensions=(".cs",),
            manifest_names=("*.csproj",),
            tool_names=("*.csproj",),
            ts_module="tree_sitter_c_sharp",
            ts_factory="language",
            ast_node_kinds={
                "class_declaration": "Class",
                "interface_declaration": "Interface",
                "struct_declaration": "Struct",
                "enum_declaration": "Enum",
                "method_declaration": "Method",
            },
        )
        cls.register(
            "ruby",
            extensions=(".rb",),
            manifest_names=("Gemfile",),
            tool_names=("Gemfile",),
            ts_module="tree_sitter_ruby",
            ts_factory="language",
            ast_node_kinds={
                "class": "Class",
                "module": "Module",
                "method": "Method",
                "singleton_method": "Method",
            },
        )
        cls.register(
            "php",
            extensions=(".php",),
            manifest_names=("composer.json",),
            tool_names=("composer.json",),
            ts_module="tree_sitter_php",
            ts_factory="language_php",
            ast_node_kinds={
                "class_declaration": "Class",
                "interface_declaration": "Interface",
                "function_declaration": "Function",
                "method_declaration": "Method",
            },
        )
        cls.register("html", extensions=(".html", ".htm"))
        cls.register("css", extensions=(".css", ".scss", ".less"))
        cls.register("bash", extensions=(".sh", ".bash"))
        cls.register("powershell", extensions=(".ps1", ".psm1"))


LanguageRegistry.register_defaults()
