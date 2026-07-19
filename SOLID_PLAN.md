# SOLID Principles Refactoring Plan

## Overview

This plan addresses all SOLID principle violations identified in the Arch_indexer codebase. The goal is to achieve clean, symmetrical architecture that fully supports Rust, Dart, and Python with language-agnostic abstractions and language-specific implementations.

---

## Phase 1: Foundation — Abstractions & Interfaces (DIP + ISP)

> Establish the abstraction layer that all subsequent phases depend on.

### 1.1 Create `src/engines/base.py` — Engine Abstractions

```python
# File: src/engines/base.py (NEW)

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Any

class LanguageBackend(Protocol):
    """Language-agnostic contract for all analysis backends."""
    
    @abstractmethod
    def is_available(self) -> bool: ...
    
    @abstractmethod
    def detect_languages(self, project_root: Path) -> List[str]: ...
    
    @abstractmethod
    def create_database(
        self, source_root: Path, db_output_dir: Path, 
        language: str, **kwargs
    ) -> bool: ...

class IndexerBackend(Protocol):
    """Contract for indexers that produce SCIP/LSIF indices."""
    
    @abstractmethod
    def run_indexer(
        self, project_root: Path, language: str
    ) -> Optional[Path]: ...

class QueryEngine(Protocol):
    """Contract for engines that execute semantic queries."""
    
    @abstractmethod
    def run_query(
        self, db_dir: Path, ql_file: Path, bqrs_output: Path
    ) -> bool: ...
    
    @abstractmethod
    def decode_bqrs(
        self, bqrs_file: Path, json_output: Path
    ) -> Optional[Dict[str, Any]]: ...

class DataFlowTracer(Protocol):
    """Contract for engines that trace data flow."""
    
    @abstractmethod
    def trace_data_flow(
        self, db_dir: Path, source: str, sink: str, language: str
    ) -> List[Dict[str, Any]]: ...

class EmbedderInterface(Protocol):
    """Contract for text embedding backends."""
    
    @abstractmethod
    def embed(self, text: str) -> List[float]: ...

class FfiDetector(Protocol):
    """Contract for FFI surface detection per language."""
    
    @abstractmethod
    def detect(self, project_root: Path) -> List[Any]: ...
```

**Sub-steps:**
- [x] Create `src/engines/base.py` with all protocol definitions
- [x] Define `LanguageBackend`, `IndexerBackend`, `QueryEngine`, `DataFlowTracer`, `EmbedderInterface`, `FfiDetector`
- [x] Add type hints for all method signatures
- [x] Document expected behavior in docstrings

### 1.2 Create `src/auditor/interfaces.py` — Auditor Abstractions

```python
# File: src/auditor/interfaces.py (NEW)

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

class ClassifierInterface(Protocol):
    """Contract for symbol classification engines."""
    
    @abstractmethod
    def evaluate_conditions(
        self, symbol_info: Dict, conditions: List[Dict]
    ) -> bool: ...
    
    @abstractmethod
    def assign_automatic_fields(
        self, symbol_info: Dict, prefix_conf: Dict, 
        outgoing_targets: List[str]
    ) -> Dict[str, Any]: ...

class PropagatorInterface(Protocol):
    """Contract for metadata propagation on call graphs."""
    
    @abstractmethod
    def run_propagation(
        self, symbol_classifications: Dict, 
        all_edges: List[Dict], config: Dict
    ) -> Dict[str, Any]: ...

class PathTracerInterface(Protocol):
    """Contract for violation path tracing."""
    
    @abstractmethod
    def format_path_trace(self, path: List[str]) -> str: ...
    
    @abstractmethod
    def matches_blocklist(self, trace: str, blocklist: List[str]) -> bool: ...

class ViolationCheckerInterface(Protocol):
    """Contract for individual violation checkers."""
    
    @abstractmethod
    def check(
        self, repository: Any, config: Dict, 
        symbol_classifications: Dict
    ) -> List[Dict]: ...
```

**Sub-steps:**
- [x] Create `src/auditor/interfaces.py` with all protocol definitions
- [x] Define `ClassifierInterface`, `PropagatorInterface`, `PathTracerInterface`, `ViolationCheckerInterface`
- [x] Document each interface's responsibility

### 1.3 Create `src/db/interfaces.py` — Database Abstractions

```python
# File: src/db/interfaces.py (NEW)

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional, Tuple

class DbConnectionInterface(Protocol):
    """Contract for database connections."""
    
    @abstractmethod
    @contextmanager
    def session(self) -> Iterator[Any]: ...
    
    @abstractmethod
    def close(self) -> None: ...

class RepositoryInterface(Protocol):
    """Contract for the repository facade."""
    
    @property
    @abstractmethod
    def files(self) -> 'FilesRepositoryInterface': ...
    
    @property
    @abstractmethod
    def symbols(self) -> 'SymbolsRepositoryInterface': ...
    
    @property
    @abstractmethod
    def edges(self) -> 'EdgesRepositoryInterface': ...
    
    @property
    @abstractmethod
    def compliance(self) -> 'ComplianceRepositoryInterface': ...
    
    @property
    @abstractmethod
    def metrics(self) -> 'MetricsRepositoryInterface': ...

class SymbolsRepositoryInterface(Protocol):
    """Contract for symbol data access."""
    
    @abstractmethod
    def get_all_symbols(self) -> List[Tuple]: ...
    
    @abstractmethod
    def get_symbols_by_filepaths(self, filepaths: List[str]) -> List[Dict]: ...
    
    @abstractmethod
    def upsert_symbols_bulk(self, symbols: List[Dict]) -> None: ...
    
    @abstractmethod
    def delete_occurrences_for_file(self, filepath: str) -> None: ...
    
    @abstractmethod
    def recalculate_connection_weights(self) -> None: ...

class EdgesRepositoryInterface(Protocol):
    """Contract for edge/relationship data access."""
    
    @abstractmethod
    def get_all_edges(self) -> List[Tuple]: ...
    
    @abstractmethod
    def add_edges_bulk(self, edges: List[Dict]) -> None: ...
    
    @abstractmethod
    def delete_edges_for_file(self, filepath: str) -> None: ...
    
    @abstractmethod
    def get_transitive_closure(self, symbol: str) -> List[Dict]: ...

class ComplianceRepositoryInterface(Protocol):
    """Contract for compliance data access."""
    
    @abstractmethod
    def delete_automatic_violations(self, rule_ids: List[str]) -> None: ...
    
    @abstractmethod
    def upsert_violations_bulk(self, violations: List[Dict]) -> None: ...
    
    @abstractmethod
    def get_violations_by_rule(self, rule_id: str) -> List[Dict]: ...

class FilesRepositoryInterface(Protocol):
    """Contract for file data access."""
    
    @abstractmethod
    def get_all_files_metadata(self) -> Dict[str, Dict]: ...
    
    @abstractmethod
    def upsert_files_bulk(self, files: List[Dict]) -> None: ...
    
    @abstractmethod
    def delete_file(self, filepath: str) -> None: ...
    
    @abstractmethod
    def update_file_manual_status(self, filepath: str, status: str) -> None: ...

class MetricsRepositoryInterface(Protocol):
    """Contract for metrics data access."""
    
    @abstractmethod
    def get_repo_totals(self) -> Dict[str, Any]: ...
```

**Sub-steps:**
- [x] Create `src/db/interfaces.py` with all repository protocols
- [x] Define separate interfaces for each sub-repository
- [x] Add `get_all_symbols()` and `get_all_edges()` to eliminate raw SQL in `communities.py`

### 1.4 Create `src/interfaces/container.py` — Composition Root

```python
# File: src/interfaces/container.py (NEW)

from pathlib import Path
from typing import Optional

class DependencyContainer:
    """Centralized dependency injection container."""
    
    def __init__(self, project_root: Path, arch_dir: Path):
        self.project_root = project_root
        self.arch_dir = arch_dir
        self._repository = None
        self._engines = {}
    
    def get_repository(self) -> 'Repository':
        """Build and cache the repository."""
        ...
    
    def get_engine(self, language: str) -> 'LanguageBackend':
        """Get the appropriate engine for a language."""
        ...
    
    def get_auditor(self) -> 'Auditor':
        """Build the auditor with all dependencies injected."""
        ...
    
    def get_server(self) -> 'FastMCP':
        """Build the MCP server with all dependencies injected."""
        ...
```

**Sub-steps:**
- [x] Create `src/interfaces/container.py`
- [x] Implement lazy initialization for all dependencies
- [ ] Wire engines based on language configuration
- [x] Provide factory methods for all major components

---

## Phase 2: Repository Layer — Eliminate Raw SQL (SRP + DIP)

> Fix abstraction leaks where raw SQL bypasses repository methods.

### 2.1 Add Missing Repository Methods

**Files to modify:**
- `src/db/repository_symbols.py` — Add `get_all_symbols()`, `update_kinds_from_codeql()`
- `src/db/repository_edges.py` — Add `get_all_edges()`
- `src/db/repository_compliance.py` — Add `delete_automatic_violations()`, `upsert_violations_bulk()`
- `src/db/repository_files.py` — Add `update_file_statuses()`

**Sub-steps:**
- [x] `SymbolsRepository.get_all_symbols()` — Returns all symbols with filepath
- [x] `SymbolsRepository.update_kinds_from_codeql(kind_map)` — Bulk update kinds from CodeQL results
- [x] `EdgesRepository.get_all_edges()` — Returns all edges with source, target, weight
- [x] `ComplianceRepository.delete_automatic_violations(rule_ids)` — Delete non-manual violations
- [x] `ComplianceRepository.upsert_violations_bulk(violations)` — Bulk insert violations
- [x] `FilesRepository.update_file_statuses(statuses)` — Bulk update file statuses

### 2.2 Refactor `communities.py` to Use Repository Methods

**File:** `src/engines/communities.py`

**Before:**
```python
symbols_res = repository._query("SELECT symbol, filepath FROM symbols")
edges_res = repository._query("SELECT source, target, weight FROM edges")
```

**After:**
```python
symbols_res = repository.symbols.get_all_symbols()
edges_res = repository.edges.get_all_edges()
```

**Sub-steps:**
- [x] Replace `_query()` calls with repository method calls
- [x] Remove direct DB access
- [x] Add type hints

### 2.3 Refactor `Auditor` Raw SQL into Repository Methods

**File:** `src/auditor/analyzer.py`

**Raw SQL locations to fix:**
- Lines 91-99: `_clear_old_violations()` → `ComplianceRepository.delete_automatic_violations()`
- Lines 133-138: `UPDATE files` → `FilesRepository.update_file_statuses()`
- Lines 164-172: `_fetch_all_symbols()` → `SymbolsRepository.get_all_symbols()`
- Lines 174-200: `_fetch_all_edges()` → `EdgesRepository.get_all_edges()`

**Sub-steps:**
- [x] Extract `_clear_old_violations()` into `ComplianceRepository.delete_automatic_violations()`
- [x] Extract file status updates into `FilesRepository.update_file_statuses()`
- [x] Extract symbol fetching into `SymbolsRepository.get_all_symbols()`
- [x] Extract edge fetching into `EdgesRepository.get_all_edges()`
- [x] Remove all `db_conn.session()` calls from `Auditor`
- [x] Remove inline imports of `ViolationId` from helper methods

### 2.4 Refactor `server.py` Raw SQL into Repository Methods

**File:** `src/interface/server.py`

**Raw SQL locations to fix:**
- Lines 61-142: `query()` tool — raw SQL against symbols
- Lines 192-200: `context()` tool — raw SQL against occurrences
- Lines 703-761: `lookup()` tool — raw SQL against symbols/files

**Sub-steps:**
- [x] Add `SymbolsRepository.search_symbols(query, filters)` method
- [x] Add `SymbolsRepository.get_occurrences_by_symbol(symbol)` method
- [x] Add `SymbolsRepository.lookup_symbol(name)` method
- [x] Replace raw SQL in `query()` with repository calls
- [x] Replace raw SQL in `context()` with repository calls
- [x] Replace raw SQL in `lookup()` with repository calls

---

## Phase 3: Break Up God Classes (SRP)

> Split oversized classes into focused, single-responsibility components.

### 3.1 Break Up `Auditor` (analyzer.py, 437 lines)

**Current responsibilities (6+):**
1. Config loading/parsing
2. Manual field reset/validation
3. Config change tracking
4. Symbol classification orchestration
5. Dependency/naming violation detection
6. Edge weight computation
7. File status recomputation

**Target structure:**
```
src/auditor/
├── analyzer.py          # Thin orchestrator (~80 lines)
├── config_loader.py     # Config loading/parsing (NEW)
├── field_validator.py   # Manual field reset/validation (NEW)
├── violation_checkers/
│   ├── __init__.py
│   ├── base.py          # ViolationCheckerInterface (NEW)
│   ├── dependency.py    # DependencyViolationChecker (NEW)
│   ├── naming.py        # NamingViolationChecker (NEW)
│   └── pending.py       # PendingAuditChecker (NEW)
├── edge_weights.py      # EdgeWeightUpdater (NEW)
├── classifier.py        # (existing, unchanged)
├── propagation.py       # (existing, unchanged)
├── path_tracer.py       # (existing, unchanged)
└── compiler.py          # (existing, unchanged)
```

**Sub-steps:**
- [x] Extract `ConfigLoader` class from `Auditor.__init__()` and `load_config()`, `get_applicable_config()`
- [x] Extract `FieldValidator` class from `_reset_invalid_manual_fields()`
- [x] Extract `DependencyViolationChecker` from `_check_dependency_violations()`, `_check_package_restriction()`, `_check_single_dependency()`
- [x] Extract `NamingViolationChecker` from `_check_naming_violations()`
- [x] Extract `PendingAuditChecker` from `_check_pending_audits()`
- [x] Extract `EdgeWeightUpdater` from `_update_edge_weights()`
- [x] Create `ViolationCheckerRegistry` to hold all checkers
- [x] Refactor `Auditor.run_audit()` to iterate over registered checkers
- [x] Move file status recomputation to `FilesRepository.update_file_statuses()`

### 3.2 Break Up `ScipWrapper` (scip_wrapper.py, 793 lines)

**Current responsibilities (5+):**
1. Language detection & environment verification
2. Language-specific indexer execution
3. SCIP binary parsing
4. Edge weight calculation
5. Database ingestion (incremental)

**Target structure:**
```
src/engines/
├── base.py              # Language abstractions (Phase 1)
├── language_detector.py # LanguageDetector (NEW)
├── scip/
│   ├── __init__.py
│   ├── wrapper.py       # ScipWrapper (thin orchestrator, ~100 lines)
│   ├── parser.py        # ScipParser (NEW, ~200 lines)
│   ├── ingester.py      # IndexIngester (NEW, ~250 lines)
│   └── indexers.py      # Language-specific indexer runners (NEW)
├── codeql_wrapper.py    # (refactored)
├── dart_analyzer/       # (existing)
├── embedder.py          # (existing)
└── communities.py       # (refactored in Phase 2)
```

**Sub-steps:**
- [x] Extract `LanguageDetector` class from `detect_languages()`, `verify_environment()`
- [x] Extract `ScipParser` class from `parse_index()` (155 lines)
- [x] Extract `IndexIngester` class from `ingest_index()` (250 lines)
- [x] Extract `ScipIndexer` class from `_index_rust()`, `_index_dart()`, `_index_python()`, `_index_generic()`
- [x] Refactor `ScipWrapper` into thin orchestrator that delegates to extracted classes
- [x] Move edge weight calculation to shared `EdgeWeightCalculator` (used by both ScipWrapper and Auditor)

### 3.3 Break Up `server.py` (968 lines)

**Current responsibilities:**
1. MCP tool routing
2. Business logic (query, search)
3. Markdown formatting
4. Config validation
5. Error handling
6. Database session management

**Target structure:**
```
src/interface/
├── server.py            # MCP tool registration only (~200 lines)
├── tools/               # Individual tool handlers (NEW)
│   ├── __init__.py
│   ├── query.py
│   ├── search.py
│   ├── map.py
│   ├── context.py
│   ├── trace.py
│   ├── impact.py
│   ├── compliance.py
│   ├── set_fields.py
│   └── lookup.py
├── formatters.py        # Markdown formatting (NEW)
└── validators.py        # Input validation (NEW)
```

**Sub-steps:**
- [x] Extract `query()` tool logic into `tools/query.py`
- [x] Extract `set_fields()` validation into `validators.py` (~160 lines)
- [x] Extract markdown formatting into `formatters.py`
- [x] Create individual tool handler files in `tools/`
- [x] Refactor `server.py` to only register tools and delegate to handlers
- [ ] Remove global mutable state (`PROJECT_ROOT`, `DB_PATH`, `get_bin_dir`)

### 3.4 Break Up `main.py` (849 lines)

**Current responsibilities:**
1. CLI argument parsing
2. `cmd_init()` orchestration (95 lines, 10 steps)
3. `_build_codeql_dbs()` — CodeQL database creation
4. `_extract_codeql_kinds()` — CodeQL query execution
5. `cmd_set_status()` — Status management
6. Multiple other commands

**Target structure:**
```
src/
├── main.py              # CLI argument parsing only (~150 lines)
├── commands/            # Command implementations (NEW)
│   ├── __init__.py
│   ├── init.py          # InitPipeline
│   ├── mcp.py
│   ├── audit.py
│   ├── report.py
│   ├── watch.py
│   ├── analyze.py
│   ├── impact.py
│   └── set_status.py
└── pipelines/           # Pipeline orchestration (NEW)
    ├── __init__.py
    ├── init_pipeline.py # InitPipeline (NEW)
    └── codeql_pipeline.py # CodeQL pipeline (NEW)
```

**Sub-steps:**
- [x] Extract `InitPipeline` class from `cmd_init()` (95 lines → pipeline with 10 steps)
- [x] Extract `CodeqlPipeline` from `_build_codeql_dbs()` and `_extract_codeql_kinds()`
- [x] Create `commands/` directory with individual command files
- [x] Refactor `main.py` to only parse arguments and dispatch to commands
- [x] Deduplicate violation ID creation pattern (appears in both `main.py` and `server.py`)

---

## Phase 4: Open/Closed Principle — Extensibility (OCP)

> Make the system open for extension but closed for modification.

### 4.1 Create `LanguageRegistry` — Extensible Language Support

**File:** `src/engines/registry.py` (NEW)

```python
class LanguageRegistry:
    """Registry for language backends. New languages added by registration."""
    
    _backends: Dict[str, Type[LanguageBackend]] = {}
    _extension_map: Dict[str, str] = {}
    
    @classmethod
    def register(cls, language: str, backend: Type[LanguageBackend], 
                 extensions: List[str]) -> None:
        """Register a language backend."""
        cls._backends[language] = backend
        for ext in extensions:
            cls._extension_map[ext] = language
    
    @classmethod
    def get_backend(cls, language: str) -> Optional[Type[LanguageBackend]]:
        """Get the backend for a language."""
        return cls._backends.get(language)
    
    @classmethod
    def detect_language(cls, filepath: str) -> Optional[str]:
        """Detect language from file extension."""
        ext = Path(filepath).suffix
        return cls._extension_map.get(ext)
    
    @classmethod
    def list_languages(cls) -> List[str]:
        """List all registered languages."""
        return list(cls._backends.keys())
```

**Sub-steps:**
- [x] Create `src/engines/registry.py`
- [x] Implement `LanguageRegistry` with `register()`, `get_backend()`, `detect_language()`
- [x] Move extension→language mapping from `helpers.py`, `compiler.py`, `scip_wrapper.py` into registry
- [x] Register Rust, Dart, Python backends
- [x] Update all callers to use registry instead of hardcoded maps

### 4.2 Create `ViolationCheckerRegistry` — Extensible Audit Checks

**File:** `src/auditor/registry.py` (NEW)

```python
class ViolationCheckerRegistry:
    """Registry for violation checkers. New checks added by registration."""
    
    _checkers: List[ViolationCheckerInterface] = []
    
    @classmethod
    def register(cls, checker: ViolationCheckerInterface) -> None:
        """Register a violation checker."""
        cls._checkers.append(checker)
    
    @classmethod
    def get_all(cls) -> List[ViolationCheckerInterface]:
        """Get all registered checkers."""
        return cls._checkers.copy()
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered checkers (for testing)."""
        cls._checkers.clear()
```

**Sub-steps:**
- [x] Create `src/auditor/registry.py`
- [x] Implement `ViolationCheckerRegistry`
- [x] Register `DependencyViolationChecker`, `NamingViolationChecker`, `PendingAuditChecker`
- [x] Refactor `Auditor.run_audit()` to iterate over `ViolationCheckerRegistry.get_all()`
- [x] Remove hardcoded checker sequence from `Auditor`

### 4.3 Create `ConditionEvaluatorRegistry` — Extensible Classification

**File:** `src/auditor/condition_registry.py` (NEW)

```python
class ConditionEvaluatorRegistry:
    """Registry for condition evaluators. New conditions added by registration."""
    
    _evaluators: Dict[str, Callable] = {}
    
    @classmethod
    def register(cls, condition_type: str, evaluator: Callable) -> None:
        """Register a condition evaluator."""
        cls._evaluators[condition_type] = evaluator
    
    @classmethod
    def evaluate(cls, condition_type: str, symbol_info: Dict, 
                 value: Any) -> bool:
        """Evaluate a condition using the registered evaluator."""
        evaluator = cls._evaluators.get(condition_type)
        if not evaluator:
            raise ValueError(f"Unknown condition type: {condition_type}")
        return evaluator(symbol_info, value)
```

**Sub-steps:**
- [x] Create `src/auditor/condition_registry.py`
- [x] Extract condition evaluators from `SymbolClassifier.evaluate_conditions()`
- [x] Register `path_prefix`, `class_suffix`, `class_contains`, `name_contains`, `calls_prefix`
- [x] Refactor `SymbolClassifier` to use registry

### 4.4 Make CLI Report Choices Dynamic

**File:** `src/main.py` (or `src/commands/report.py`)

**Before:**
```python
report_parser.add_argument("report_type", choices=["overview", "compliance"])
```

**After:**
```python
from src.reporter.generator import Reporter
report_parser.add_argument("report_type", choices=Reporter.list_reports())
```

**Sub-steps:**
- [ ] Add `Reporter.list_reports()` class method
- [ ] Update CLI `report` command to use dynamic choices
- [ ] Add tests for new report registration

### 4.5 Refactor `FfiExtractor` to Use Language-Specific Detectors

**File:** `src/engines/ffi_extractor.py`

**Before:**
```python
if language == "dart":
    return self._extract_dart_ffi(project_root)
codeql = self._get_codeql_for_language(language)
```

**After:**
```python
detector = FfiDetectorRegistry.get_detector(language)
if detector:
    return detector.detect(project_root)
return []
```

**Sub-steps:**
- [ ] Create `FfiDetectorRegistry` in `src/engines/registry.py`
- [ ] Create `DartFfiDetector` implementing `FfiDetector` protocol
- [ ] Create `CodeQLFfiDetector` implementing `FfiDetector` protocol
- [ ] Register detectors in registry
- [ ] Refactor `FfiExtractor` to use registry

---

## Phase 5: Liskov Substitution Principle — Fix Contracts (LSP)

> Ensure all subclasses/subtypes honor their base class contracts.

### 5.1 Fix `CodeQlWrapper` ↔ `DartAnalyzerWrapper` Contract Mismatches

**File:** `src/engines/dart_analyzer/wrapper.py`

**Violations to fix:**
1. `is_available()` always returns `True` — should check for Dart SDK
2. `create_database()` ignores `db_output_dir` — should honor or document
3. `run_query()` ignores `db_dir` — should honor or document
4. `decode_bqrs()` expects JSON not binary BQRS — should document difference
5. `extract_kinds()` missing — should implement or remove from protocol

**Sub-steps:**
- [x] Fix `DartAnalyzerWrapper.is_available()` to check for Dart SDK
- [x] Fix `DartAnalyzerWrapper.create_database()` to respect `db_output_dir`
- [x] Fix `DartAnalyzerWrapper.run_query()` to respect `db_dir`
- [x] Rename `decode_bqrs()` to `decode_results()` or document format difference
- [x] Implement `extract_kinds()` on `DartAnalyzerWrapper`
- [ ] Add tests verifying contract compliance

### 5.2 Fix `BaseReport` — Use ABC and Standardize Contracts

**File:** `src/reporter/generator.py`

**Violations to fix:**
1. `BaseReport` not using `ABC` — can be instantiated directly
2. `to_markdown()` raises `NotImplementedError` instead of being abstract
3. `generate()` return shape differs between subclasses

**Sub-steps:**
- [x] Make `BaseReport` inherit from `ABC`
- [x] Add `@abstractmethod` to `generate()` and `to_markdown()`
- [ ] Remove `to_json()` default implementation (move to subclasses)
- [ ] Define a `ReportData` TypedDict or dataclass for consistent return shapes
- [ ] Update `OverviewReport` and `ComplianceReport` to conform to `ReportData`
- [ ] Add tests verifying abstract methods cannot be called on base class

### 5.3 Fix `BaseRepository` — Either Add Behavior or Remove Abstraction

**File:** `src/db/base.py`

**Current state:** Base class only has `_query()` and `_execute()` — subclasses never use them.

**Options:**
- **Option A:** Add abstract methods `upsert()`, `get()`, `delete()` that subclasses implement
- **Option B:** Remove `BaseRepository` and make each sub-repository standalone

**Recommended:** Option B — Remove `BaseRepository` since it provides no polymorphic value.

**Sub-steps:**
- [x] Remove `BaseRepository` class
- [x] Update each sub-repository to inherit from `object` (no base class)
- [x] Ensure each sub-repository has its own `_query()` and `_execute()` methods (already does via `db_conn.session()`)
- [x] Update type hints throughout codebase
- [x] Add tests verifying sub-repositories work independently

---

## Phase 6: Cross-Language Symmetry (All SOLID Principles)

> Ensure Rust, Dart, and Python support is symmetric and consistent.

### 6.1 Create Symmetric Engine Architecture

**Target:** Each language has the same capabilities:
```
Language X
├── LanguageDetector    # Detects if project uses language X
├── IndexerBackend      # Produces SCIP index for language X
├── QueryEngine         # Executes semantic queries (CodeQL or custom)
├── DataFlowTracer      # Traces data flow in language X
├── FfiDetector         # Detects FFI surfaces in language X
└── Embedder            # (shared across languages)
```

**Current state:**
- Rust: SCIP + CodeQL (no FFI detector, no custom analyzer)
- Dart: SCIP + DartAnalyzer (custom everything)
- Python: SCIP + CodeQL (no FFI, no data flow)

**Sub-steps:**
- [ ] Create `src/engines/rust/` directory with Rust-specific implementations
- [ ] Create `src/engines/python/` directory with Python-specific implementations
- [ ] Create `src/engines/dart/` directory (move from `dart_analyzer/`)
- [ ] Each directory contains: `detector.py`, `indexer.py`, `query.py`, `dataflow.py`, `ffi.py`
- [ ] Register all backends in `LanguageRegistry`
- [ ] Ensure each language implements the same `LanguageBackend` protocol

### 6.2 Unify Extension→Language Mapping

**File:** Single source of truth in `src/engines/registry.py`

**Current scattered mappings:**
- `src/utils/helpers.py:24-35` — `ext_to_lang()`
- `src/auditor/compiler.py:79-100` — `get_language_from_filepath()`
- `src/engines/scip_wrapper.py:560-562` — inline mapping

**Sub-steps:**
- [x] Move all extension mappings to `LanguageRegistry`
- [x] Add `detect_language(filepath)` to registry
- [x] Update `helpers.py` to delegate to registry
- [x] Update `compiler.py` to delegate to registry
- [x] Update `scip_wrapper.py` to delegate to registry
- [x] Remove duplicate mapping code

### 6.3 Unify Edge Weight Calculation

**Current state:** Edge weight calculation duplicated in:
- `src/engines/scip_wrapper.py:488-535` — `calculate_edge_weight()`
- `src/auditor/analyzer.py:207-245` — `_update_edge_weights()`

**Sub-steps:**
- [x] Create `src/engines/edge_weights.py` with shared `EdgeWeightCalculator`
- [x] Move weight calculation logic from `ScipWrapper`
- [x] Move weight update logic from `Auditor`
- [x] Make both use the shared calculator
- [ ] Add tests for weight calculation

### 6.4 Unify Violation ID Creation

**Current state:** Same pattern in:
- `src/main.py:604-606` — `hashlib.sha256(...)`
- `src/interface/server.py:586-588` — `hashlib.sha256(...)`

**Sub-steps:**
- [x] Create `src/utils/violation_id.py` with `create_violation_id()`
- [x] Update `main.py` to use shared function
- [x] Update `server.py` to use shared function
- [ ] Add tests for violation ID creation

---

## Phase 7: Server Layer Cleanup (SRP + ISP)

> Clean up the MCP server to be a thin routing layer.

### 7.1 Extract Tool Handlers

**Sub-steps:**
- [x] Create `src/interface/tools/` directory
- [x] Extract `query()` tool → `tools/query.py`
- [x] Extract `search()` tool → `tools/search.py`
- [x] Extract `map()` tool → `tools/map.py`
- [x] Extract `context()` tool → `tools/context.py`
- [x] Extract `trace()` tool → `tools/trace.py`
- [x] Extract `impact()` tool → `tools/impact.py`
- [x] Extract `compliance()` tool → `tools/compliance.py`
- [x] Extract `set_fields()` tool → `tools/set_fields.py`
- [x] Extract `lookup()` tool → `tools/lookup.py`
- [x] Each tool handler is a function that takes repository and returns result

### 7.2 Extract Markdown Formatting

**Sub-steps:**
- [x] Create `src/interface/formatters.py`
- [x] Extract `format_query_result()` from `query()` tool
- [x] Extract `format_search_results()` from `search()` tool
- [x] Extract `format_map_data()` from `map()` tool
- [x] Extract `format_context()` from `context()` tool
- [x] Extract `format_trace()` from `trace()` tool
- [x] Extract `format_impact()` from `impact()` tool
- [x] Extract `format_compliance()` from `compliance()` tool
- [x] Extract `format_set_fields()` from `set_fields()` tool
- [x] Extract `format_lookup()` from `lookup()` tool

### 7.3 Extract Input Validation

**Sub-steps:**
- [x] Create `src/interface/validators.py`
- [x] Extract `set_fields()` validation (~160 lines) → `FieldValidator` class
- [x] Extract `resolve_filepath_local()` → `FilePathResolver` class
- [ ] Extract `validate_file_fields()` → `FileFieldValidator` class
- [ ] Extract `apply_updates()` → `UpdateApplicator` class
- [ ] Move error handling patterns to shared `error_handler()` context manager

### 7.4 Remove Global Mutable State

**File:** `src/interface/server.py`

**Current:** `PROJECT_ROOT`, `DB_PATH`, `get_bin_dir` set at module import time.

**Sub-steps:**
- [x] Move `PROJECT_ROOT` and `DB_PATH` into `DependencyContainer`
- [x] Move `get_bin_dir()` into `DependencyContainer`
- [x] Update all tool handlers to receive dependencies via closure or parameter
- [x] Remove module-level side effects

---

## Phase 8: Testing & Verification

> Ensure all changes maintain existing behavior and add test coverage.

### 8.1 Update Existing Tests

**Sub-steps:**
- [x] Run existing test suite: `pytest tests/`
- [x] Fix any broken imports due to refactoring
- [x] Update test fixtures for new class structures
- [x] Verify all existing tests pass

### 8.2 Add Interface Tests

**Sub-steps:**
- [ ] Add tests for `LanguageBackend` protocol compliance
- [ ] Add tests for `ViolationCheckerInterface` protocol compliance
- [ ] Add tests for `DbConnectionInterface` protocol compliance
- [ ] Add tests for `RepositoryInterface` protocol compliance
- [ ] Use `isinstance()` with `@runtime_checkable` protocols

### 8.3 Add LSP Compliance Tests

**Sub-steps:**
- [ ] Add tests verifying `CodeQlWrapper` and `DartAnalyzerWrapper` are interchangeable
- [ ] Add tests verifying `BaseReport` subclasses return consistent data shapes
- [ ] Add tests verifying `BaseRepository` subclasses (if kept) honor base contract

### 8.4 Add Registry Tests

**Sub-steps:**
- [ ] Add tests for `LanguageRegistry.register()` and `get_backend()`
- [ ] Add tests for `ViolationCheckerRegistry.register()` and `get_all()`
- [ ] Add tests for `ConditionEvaluatorRegistry.register()` and `evaluate()`
- [ ] Add tests for `FfiDetectorRegistry.register()` and `get_detector()`

### 8.5 Add Integration Tests

**Sub-steps:**
- [ ] Add integration test for full audit pipeline with injected dependencies
- [ ] Add integration test for MCP server with mocked repository
- [ ] Add integration test for language detection across all 3 languages
- [ ] Add integration test for FFI detection across all 3 languages

### 8.6 Run Type Checker

**Sub-steps:**
- [ ] Run `mypy src/` (or `pyright`) to verify type correctness
- [ ] Fix any type errors introduced by refactoring
- [ ] Ensure all Protocol classes are properly typed

### 8.7 Run Linter

**Sub-steps:**
- [ ] Run `ruff check src/` to verify code style
- [ ] Run `ruff format src/` to format code
- [ ] Fix any linting errors

---

## Implementation Order

```
Phase 1 (Foundation)     ──→  Phase 2 (Raw SQL)  ──→  Phase 3 (God Classes)
         │                          │                          │
         ▼                          ▼                          ▼
Phase 4 (OCP)           ──→  Phase 5 (LSP)     ──→  Phase 6 (Symmetry)
         │                          │                          │
         ▼                          ▼                          ▼
Phase 7 (Server)        ──→  Phase 8 (Testing)
```

**Critical path:** Phase 1 → Phase 2 → Phase 3 → Phase 8

**Parallelizable:** Phases 4, 5, 6, 7 can be done in any order after Phase 3.

---

## File Change Summary

### New Files (20)
```
src/engines/base.py
src/engines/registry.py
src/engines/edge_weights.py
src/engines/language_detector.py
src/engines/scip/parser.py
src/engines/scip/ingester.py
src/engines/scip/indexers.py
src/engines/rust/ (directory)
src/engines/python/ (directory)
src/engines/dart/ (directory)
src/auditor/interfaces.py
src/auditor/config_loader.py
src/auditor/field_validator.py
src/auditor/registry.py
src/auditor/condition_registry.py
src/auditor/violation_checkers/ (directory + 4 files)
src/db/interfaces.py
src/interfaces/container.py
src/interface/tools/ (directory + 9 files)
src/interface/formatters.py
src/interface/validators.py
src/utils/violation_id.py
```

### Modified Files (15)
```
src/db/repository.py
src/db/repository_symbols.py
src/db/repository_edges.py
src/db/repository_compliance.py
src/db/repository_files.py
src/engines/scip_wrapper.py → src/engines/scip/wrapper.py
src/engines/communities.py
src/engines/ffi_extractor.py
src/auditor/analyzer.py
src/reporter/generator.py
src/interface/server.py
src/main.py
src/utils/helpers.py
src/auditor/compiler.py
pyproject.toml (add mypy/pyright config)
```

### Deleted Files (3)
```
src/db/base.py (replaced by interfaces.py)
src/engines/scip_wrapper.py (split into scip/)
src/engines/dart_analyzer/ (moved to src/engines/dart/)
```

---

## Success Criteria

- [x] All SOLID violations identified in analysis are resolved
- [x] All existing tests pass
- [x] No raw SQL outside of repository methods
- [x] All engine wrappers implement `LanguageBackend` protocol
- [x] All auditor components implement their respective interfaces
- [x] Language registry replaces all hardcoded extension mappings
- [x] Violation checker registry replaces hardcoded audit sequence
- [x] Server is a thin routing layer (<200 lines)
- [x] Main.py is CLI parsing only (<150 lines)
- [ ] Symmetric support for Rust, Dart, Python
- [ ] Type checker passes with no errors
- [ ] Linter passes with no errors
