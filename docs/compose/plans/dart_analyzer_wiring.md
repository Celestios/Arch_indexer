# Dart Analyzer Wiring Plan

## Overview

Wire `DartAnalyzerWrapper` into 4 call sites. All internal plumbing is complete - only call sites need updates.

## Wiring Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    Current State (Broken)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  main.py:304        FfiExtractor()         ← no backends        │
│  watcher.py:129     FfiExtractor()         ← no backends        │
│  server.py:442      CodeQlWrapper()        ← Dart only, no fallback│
│  main.py:276-294    CodeQL DB creation     ← skips Dart         │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                    Target State (Wired)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  main.py:276-294    Creates dart_analyzer_db for Dart            │
│  main.py:304        FfiExtractor(codeql, dart_analyzer)          │
│  watcher.py:129     FfiExtractor(codeql, dart_analyzer)          │
│  server.py:442      Tries dart_analyzer, falls back to CodeQL    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Wiring 1: `src/main.py` (lines 276-294) — Database Creation

### Current Code
```python
# Line 276-294
if build_cql:
    print("\n--- Running CodeQL Database Generator ---")
    try:
        from engines.codeql_wrapper import CodeQlWrapper
        codeql = CodeQlWrapper(bin_dir)
        for lang in cql_langs:
            db_output_dir = arch_dir / f"codeql_db_{lang}"
            print(f"\n[CodeQL] Building database for {lang}...")
            success = codeql.create_database(
                source_root=project_root,
                db_output_dir=db_output_dir,
                language=lang
            )
            # ...
```

### What to Change
Add Dart analyzer database creation **before** the CodeQL loop, or as a parallel path.

### New Code
```python
# Line 276-294 - Replace with:
dart_analyzer = None

# Create Dart analyzer database (lighter, no compiler needed)
if "dart" in selected_languages:
    try:
        from engines.dart_analyzer import DartAnalyzerWrapper
        dart_analyzer = DartAnalyzerWrapper(arch_dir)
        if dart_analyzer.is_available():
            print("\n--- Running Dart Analyzer Database Generator ---")
            dart_analyzer.create_database(
                source_root=project_root,
                db_output_dir=arch_dir / "dart_analyzer_db",
                language="dart"
            )
        else:
            print("\n[DartAnalyzer] analyzer package not available, skipping.")
            dart_analyzer = None
    except ImportError:
        print("\n[DartAnalyzer] Failed to import, skipping.")
        dart_analyzer = None

# Create CodeQL databases for supported languages
if build_cql:
    print("\n--- Running CodeQL Database Generator ---")
    try:
        from engines.codeql_wrapper import CodeQlWrapper
        codeql = CodeQlWrapper(bin_dir)
        # Filter out dart from cql_langs (CodeQL doesn't support it)
        cql_langs_filtered = [l for l in cql_langs if l != "dart"]
        for lang in cql_langs_filtered:
            db_output_dir = arch_dir / f"codeql_db_{lang}"
            print(f"\n[CodeQL] Building database for {lang}...")
            success = codeql.create_database(
                source_root=project_root,
                db_output_dir=db_output_dir,
                language=lang
            )
            # ... (keep existing success/failure handling)
```

### Key Points
- `dart_analyzer` variable created here, passed to FFI extractor later
- Dart excluded from CodeQL loop (CodeQL doesn't support it)
- Falls back gracefully if analyzer package not installed

---

## Wiring 2: `src/main.py` (line 304) — FFI Extraction

### Current Code
```python
# Line 300-304
from engines.ffi_extractor import FfiExtractor
from engines.ffi_matcher import FfiMatcher
from engines.ffi_linker import FfiLinker

extractor = FfiExtractor()
surfaces = extractor.extract_all(project_root, languages=selected_languages)
```

### What to Change
Pass backends to `FfiExtractor`.

### New Code
```python
# Line 300-304 - Replace with:
from engines.ffi_extractor import FfiExtractor
from engines.ffi_matcher import FfiMatcher
from engines.ffi_linker import FfiLinker

# Get CodeQL wrapper if available
codeql = None
if cql_ready:
    from engines.codeql_wrapper import CodeQlWrapper
    codeql = CodeQlWrapper(bin_dir)

# FfiExtractor now receives both backends
extractor = FfiExtractor(codeql_wrapper=codeql, dart_analyzer=dart_analyzer)
surfaces = extractor.extract_all(project_root, languages=selected_languages)
```

### Key Points
- `dart_analyzer` variable from Wiring 1 is in scope
- `codeql` created here (or reuses from Wiring 1 if in scope)
- `FfiExtractor._extract_dart_ffi()` automatically picks best backend

---

## Wiring 3: `src/interface/server.py` (lines 440-459) — trace_data_flow

### Current Code
```python
# Line 440-459
db_conn = DbConnection(DB_PATH)
try:
    from engines.codeql_wrapper import CodeQlWrapper
    bin_dir = get_bin_dir()
    codeql = CodeQlWrapper(bin_dir)
except Exception as e:
    db_conn.close()
    return f"Error importing CodeQL Wrapper: {e}"

db_dir = ARCH_DIR / "codeql_db"
if not db_dir.exists():
    db_conn.close()
    return f"Error: CodeQL database not found at {db_dir}. Please create it first."

try:
    steps = codeql.trace_data_flow(db_dir, source, sink)
except Exception as e:
    return f"Error running data flow trace: {e}"
finally:
    db_conn.close()
```

### What to Change
Try Dart analyzer first, fall back to CodeQL. Use correct `db_dir` for each.

### New Code
```python
# Line 440-459 - Replace with:
db_conn = DbConnection(DB_PATH)
steps = []

# Try Dart analyzer first (lighter, no compiler needed)
try:
    from engines.dart_analyzer import DartAnalyzerWrapper
    dart_wrapper = DartAnalyzerWrapper(ARCH_DIR)
    if dart_wrapper.is_available():
        dart_db = ARCH_DIR / "dart_analyzer_db"
        if dart_db.exists():
            steps = dart_wrapper.trace_data_flow(dart_db, source, sink)
except Exception:
    pass

# Fallback to CodeQL if Dart analyzer didn't find a path
if not steps:
    try:
        from engines.codeql_wrapper import CodeQlWrapper
        bin_dir = get_bin_dir()
        codeql = CodeQlWrapper(bin_dir)
        db_dir = ARCH_DIR / "codeql_db"
        if db_dir.exists() and codeql.is_available():
            steps = codeql.trace_data_flow(db_dir, source, sink)
    except Exception:
        pass

db_conn.close()

if not steps:
    return f"## Data Flow Trace\n\nNo flow path found between source `{source}` and sink `{sink}`."

md = [f"## Data Flow Trace: Path Found ({len(steps)} steps)\n"]
for i, step in enumerate(steps, 1):
    md.append(f"{i}. `{step['symbol']}` (`{step['filepath']}:L{step['line']}`)")
md.append("")

return "\n".join(md)
```

### Key Points
- Tries Dart analyzer first (faster, no CLI dependency)
- Falls back to CodeQL if analyzer not available or no path found
- Both return same `[{"symbol", "filepath", "line"}]` format
- Removes hardcoded `db_dir` check (each wrapper checks its own DB)

---

## Wiring 4: `src/change_tracker/watcher.py` (line 129) — File Watcher FFI

### Current Code
```python
# Line 125-129
from engines.ffi_extractor import FfiExtractor
from engines.ffi_matcher import FfiMatcher
from engines.ffi_linker import FfiLinker

extractor = FfiExtractor()
```

### What to Change
Pass backends to `FfiExtractor`.

### New Code
```python
# Line 125-129 - Replace with:
from engines.ffi_extractor import FfiExtractor
from engines.ffi_matcher import FfiMatcher
from engines.ffi_linker import FfiLinker

# Create backends for FFI extraction
dart_wrapper = None
codeql_wrapper = None
try:
    from engines.dart_analyzer import DartAnalyzerWrapper
    dart_wrapper = DartAnalyzerWrapper(arch_dir)
    if not dart_wrapper.is_available():
        dart_wrapper = None
except ImportError:
    pass

try:
    from engines.codeql_wrapper import CodeQlWrapper
    codeql_wrapper = CodeQlWrapper(bin_dir)
    if not codeql_wrapper.is_available():
        codeql_wrapper = None
except Exception:
    pass

extractor = FfiExtractor(codeql_wrapper=codeql_wrapper, dart_analyzer=dart_wrapper)
```

### Key Points
- Watcher needs both backends for FFI re-linking on file changes
- Graceful fallback if either backend unavailable
- `arch_dir` and `bin_dir` already in scope from parent function

---

## Dependency Flow

```
main.py (init)
├── Creates dart_analyzer = DartAnalyzerWrapper(arch_dir)
├── Creates codeql = CodeQlWrapper(bin_dir)
├── Passes both to FfiExtractor
└── dart_analyzer.create_database() called

server.py (trace_data_flow)
├── Tries dart_wrapper.trace_data_flow()
└── Falls back to codeql.trace_data_flow()

watcher.py (file change)
├── Creates dart_wrapper = DartAnalyzerWrapper(arch_dir)
├── Creates codeql_wrapper = CodeQlWrapper(bin_dir)
└── Passes both to FfiExtractor
```

---

## Rollback Strategy

When CodeQL adds Dart support:

1. Remove `dart_analyzer` parameter from `FfiExtractor()` calls
2. Remove `DartAnalyzerWrapper` imports
3. `FfiExtractor` will use CodeQL for Dart automatically

**No code changes needed in `FfiExtractor` itself** — it already supports both backends.

---

## Testing Checklist

- [ ] `dart_analyzer_db/` created during `arch init` when Dart project detected
- [ ] `FfiExtractor` returns Dart FFI surfaces from analyzer
- [ ] `FfiExtractor` returns Rust FFI surfaces from CodeQL
- [ ] `FfiMatcher` matches Dart ↔ Rust FFI surfaces correctly
- [ ] `trace_data_flow` in server.py returns results from analyzer
- [ ] `trace_data_flow` falls back to CodeQL when analyzer unavailable
- [ ] Watcher re-runs FFI linking on Dart file changes
- [ ] All 72 existing tests still pass

---

## Effort Estimate

| Wiring | Files Changed | Lines Changed | Time |
|--------|---------------|---------------|------|
| 1. main.py DB creation | 1 | ~20 lines | 30min |
| 2. main.py FFI extraction | 1 | ~5 lines | 15min |
| 3. server.py trace_data_flow | 1 | ~25 lines | 45min |
| 4. watcher.py FFI | 1 | ~15 lines | 30min |
| Testing | - | - | 1h |
| **Total** | **3 files** | **~65 lines** | **~2.5h** |
