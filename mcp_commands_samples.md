# Architectural MCP Commands Output Archive

This file archives samples of outputs from the various `arch` MCP tools executed during the session on June 29, 2026.

---

## 1. Compliance Audit (`arch/audit`)
**Tool Description**: Runs the project-wide architectural boundary rules compliance audit based on Layer/Tier rules in `config.json`.

### Sample Output:
```markdown
## Compliance Audit

**No boundary rule violations found** project-wide.
```

---

## 2. Blueprint Map (`arch/map`)
**Tool Description**: Provides a high-level architectural map of the repository, including total counts, automatically detected symbol communities (using Label Propagation), inter-module call weights, and the most connected hub symbols in each community.

### Sample Output:
```markdown
## Repository Architectural Blueprint Map

### Project Totals
- **Files Indexed**: 315
- **Symbols Registered**: 12048
- **Dependencies (Call Graph Edges)**: 13412
- **Active Architectural Violations**: 0

### Detected Architectural Communities
#### Community: `external/` (3583 symbol(s))
  - **Key Hub Symbols**:
    * `scip-dart pub dart:core 3.12.0 dart:core/string.dart/String#` (Connections: 849)
    * `scip-dart pub dart:core 3.12.0 dart:core/double.dart/double#` (Connections: 345)
    * `scip-dart pub dart:core 3.12.0 dart:core/list.dart/List#` (Connections: 325)

#### Community: `lib/src/rust/domain/` (1942 symbol(s))
  - **Key Hub Symbols**:
    * `scip-dart pub dart:core 3.12.0 dart:core/int.dart/int#` (Connections: 354)
    * `scip-dart pub dart:core 3.12.0 dart:core/object.dart/Object#` (Connections: 264)
    * `scip-dart pub mycelium 0.3.0+4 lib\src\rust\domain\patches.freezed.dart/$Res#` (Connections: 94)

#### Community: `rust/src/` (710 symbol(s))
  - **Key Hub Symbols**:
    * `rust-analyzer cargo rust_lib_mycelium 0.3.0 frb_generated/` (Connections: 814)
    * `rust-analyzer cargo rust_lib_mycelium 0.3.0 crate/` (Connections: 390)
    * `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/` (Connections: 127)

### Inter-Community Call Dependencies
- `external/` ──[141 call(s)]──> `lib/src/rust/domain/`
- `external/` ──[123 call(s)]──> `lib/src/rust/`
- `lib/features/graph/models/` ──[44 call(s)]──> `external/`
- `lib/features/graph/models/` ──[16 call(s)]──> `lib/src/rust/domain/`
```

---

## 3. Query (`arch/query`)
**Tool Description**: Runs keyword and semantic searches over symbols, docstrings, and files in the codebase. Accepts multiple search terms as a list of strings.

### Sample Output:
```markdown
## Search Results for: "RelationEngine"

### 1. Symbol Name Matches (Keyword Search)
1. **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\engine\interaction_context.dart`/QueryCapability#`<get>relationEngine`.**
   - **File**: `lib\features\graph\engine\interaction_context.dart`
2. **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\store\graph_data_controller.dart`/GraphDataController#relationEngine.**
   - **File**: `lib\features\graph\store\graph_data_controller.dart`

### 2. Semantic Docstring Matches
1. **scip-dart pub mycelium 0.3.0+4 `lib\src\rust\domain\styles.freezed.dart`/RelationStylePatterns#** (Similarity: 0.63)
   - **Doc**: Adds pattern-matching-related methods to [RelationStyle].

## Search Results for: "Mutex"

### 1. Symbol Name Matches (Keyword Search)
1. **scip-dart pub mycelium 0.3.0+4 `lib\src\rust\frb_generated.dart`/RustLibApi#`<get>rust_arc_increment_strong_count_ArcMutexRelationEngine`.**
   - **File**: `lib\src\rust\frb_generated.dart`
```

---

## 4. Structural Context (`arch/context`)
**Tool Description**: Provides a compact structural index (Table of Contents) of all classes, methods, and functions declared in the specified file(s), along with their precise line ranges.

### Sample Output (from `lib/features/graph/store/graph_data_controller.dart`):
```markdown
## File Index: `lib/features/graph/store/graph_data_controller.dart`

### Methods & Functions
- **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\store\graph_data_controller.dart`/GraphDataController#** [L34-34]
  * *Docstring*: High-level orchestrator utilizing Clean Class Composition.
- **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\store\graph_data_controller.dart`/GraphDataController#store.** [L42-42]
- **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\store\graph_data_controller.dart`/GraphDataController#nodeMutations.** [L47-47]
- **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\store\graph_data_controller.dart`/GraphDataController#relationEngine.** [L52-52]
- **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\store\graph_data_controller.dart`/GraphDataController#loadGraph().** [L216-216]
- **scip-dart pub mycelium 0.3.0+4 `lib\features\graph\store\graph_data_controller.dart`/GraphDataController#undo().** [L250-250]
```

### Sample Output (from `rust/src/domain/relations.rs`):
```markdown
## File Index: `rust/src/domain/relations.rs`

### Methods & Functions
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/IRelation#** [L6-6]
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/impl#[IRelation][IsTable]get_key().** [L16-16]
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/impl#[IRelation][SurrealValue]from_value().** [L26-26]
  * *Docstring*: Attempts to convert a SurrealDB value into this type
```

---

## 5. Blast Radius Impact (`arch/impact`)
**Tool Description**: Performs blast radius analysis for a symbol by computing the transitive closure of its upstream callers and downstream callees.

### Sample Output (for struct `IRelation`):
```markdown
## Blast Radius for: `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/IRelation#`

### ── Upstream Callers (Who calls this?)
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 templates/** [Depth: 1]
  * Path: `0 templates/` ──> `0 domain/relations/IRelation#`
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 persistence/repo/relations/impl#[Repository]create_relation().** [Depth: 1]
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 bridge/api/impl#[AppHandle]create_relation().** [Depth: 1]
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 frb_generated/impl#[`domain::relations::IRelation`][`IntoIntoDart<Self>`]into_into_dart().** [Depth: 1]
- **rust-analyzer cargo rust_lib_mycelium 0.3.0 persistence/repo/** [Depth: 2]
  * Path: `0 persistence/repo/` ──> `0 persistence/repo/analysis/` ──> `0 domain/relations/IRelation#`

### ── Downstream Callees (What does this call?)
*No transitive downstream callees found.*
```

---

## 6. Data Flow Trace (`arch/trace`)
**Tool Description**: Traces the data flow path from a source symbol to a sink symbol using CodeQL analysis.

### Execution result on this workspace:
`Error running data flow trace: CodeQL CLI is not available.`
*(Note: Requires the CodeQL CLI to be installed and configured in the system environment path to map AST data flows.)*

---

## 7. Dynamic Context Compilation (`arch/compile_context`)
**Tool Description**: Compiles a deterministic markdown-formatted architectural context document starting from a focal symbol, traversing its call graph neighborhood.

### Sample Output (Focal symbol: `from_value`, Radius: 1, Resolution: signature):
```markdown
# Dynamic Architectural Context Compilation
Generated dynamically by the Arch-mcp Context Compiler.

## 1. Architectural Context Bounds
- **Focal Target**: `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/impl#[IRelation][SurrealValue]from_value().`
- **Search Direction**: `both`
- **Traversed Radius**: `1` hops
- **Resolution Profile**: `signature`
- **Total Resolved Nodes**: `4`

---
## 2. Focal Core Target Node
- **Symbol ID**: `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/impl#[IRelation][SurrealValue]from_value().`
- **Filepath**: `rust\src\domain\relations.rs`
- **AST Kind**: `'UnspecifiedKind'`
- **Docstring**:
  Attempts to convert a SurrealDB value into this type

#### Active Code Block:
```rust
    fn from_value(value: Value) -> Result<Self, surrealdb::types::Error> {
```

---
## 3. Traversed Subgraph Neighbors

### Neighbor #1: `rust-analyzer cargo rust_lib_mycelium 0.3.0 persistence/repo/nodes/`
- **Symbol ID**: `rust-analyzer cargo rust_lib_mycelium 0.3.0 persistence/repo/nodes/`
- **Filepath**: `rust\src\persistence\repo\nodes.rs`

### Neighbor #2: `rust-analyzer cargo rust_lib_mycelium 0.3.0 bridge/api/`
- **Symbol ID**: `rust-analyzer cargo rust_lib_mycelium 0.3.0 bridge/api/`
- **Filepath**: `rust\src\bridge\api.rs`

### Neighbor #3: `rust-analyzer cargo rust_lib_mycelium 0.3.0 persistence/repo/relations/`
- **Symbol ID**: `rust-analyzer cargo rust_lib_mycelium 0.3.0 persistence/repo/relations/`
- **Filepath**: `rust\src\persistence\repo\relations.rs`
```

---

## 8. File & Symbol Details Lookup (`arch/index`)
**Tool Description**: Looks up details, metadata, and relationships for a file module or code symbol.

### Sample Output (Target: `rust/src/domain/relations.rs`):
```markdown
## File Module: `rust\src\domain\relations.rs`

- **Language**: `rust`
- **Computed Status**: `COMPLIANT`
- **Manual status**: `COMPLIANT`
- **Pending Audit**: `True`
- **Justification**: *New file, pending initial audit*

### Symbols Declared in File
| Symbol | Kind | Signature |
| :--- | :--- | :--- |
| `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/` | `UnspecifiedKind` | `` |
| `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/IRelation#` | `UnspecifiedKind` | `` |
| `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/impl#[IRelation][SurrealValue]from_value().` | `UnspecifiedKind` | `` |
```

### Sample Output (Target: `from_value` code symbol):
```markdown
## Code Symbol: `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/impl#[IRelation][SurrealValue]from_value().`

- **Filepath**: `rust\src\domain\relations.rs`
- **Kind**: `UnspecifiedKind`
- **Docstring**:
  Attempts to convert a SurrealDB value into this type

### Symbol Occurrences
| Filepath | Line Range | Role (Definition=1, Ref=2) |
| :--- | :--- | :--- |
| `rust\src\persistence\repo\relations.rs` | L40-40 | 0 |
| `rust\src\domain\relations.rs` | L26-26 | 1 |

### Call Graph Relationships
| Source (Caller) | Target (Callee) | Relation |
| :--- | :--- | :--- |
| `rust-analyzer cargo rust_lib_mycelium 0.3.0 persistence/repo/relations/` | `rust-analyzer cargo rust_lib_mycelium 0.3.0 domain/relations/impl#[IRelation][SurrealValue]from_value().` | `Calls` |
```



