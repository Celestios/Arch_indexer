# PyInstaller Binary Packaging

## Synchronizing datas manifest with dual-engine architecture in PyInstaller specification

**Id:** e0aee2d1-9e4e-4ed4-8b55-6b5c2ee8b213
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer directive, 2026-11-17
**Revisit when:** Packaging migrates to Nuitka, py2exe, or multi-platform container images

The PyInstaller spec file `arch.spec` bundles `src/db/schema.sql`, `src/graph_builder/circuit_config.json`, and all Tree-sitter language query files (`src/engines/treesitter/queries/*`), while pruning obsolete references to deleted legacy CodeQL query folders (`src/engines/queries/*`) and deleted helper packages (`src/engines/dart_analyzer/helper`).

**Reason:** Following the architectural redesign that replaced the external Dart analyzer and CodeQL engines with embedded Tree-sitter parsers and SCIP compilation, the PyInstaller build failed with missing data directory errors. Pruning dead asset references and bundling the active `.scm` grammar queries enables building a self-contained, single-file Windows executable (`dist/arch.exe`) with all required runtime assets.

**Rejected alternative:** Leaving data paths to dynamic discovery or loose filesystem deployment was rejected because `arch.exe` is intended to run as a portable, standalone binary on machines without a local Python development environment or cloned repository source tree.
