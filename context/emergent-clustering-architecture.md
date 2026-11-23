# Emergent Clustering Architecture & Parameter-Free Hierarchical Decomposition

## Standalone clustering package with sparse O(E) Louvain modularity and self-loop preservation

**Id:** c440f279-f2de-455b-a290-7fe3f078f9c2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-24
**Revisit when:** native DuckDB graph extension provides zero-copy C++ Louvain modularity and community contraction directly in-database

Parameter-free hierarchical clustering was implemented as a standalone domain package (`src/clustering/`) rather than a monolithic file or an extension inside `src/engines/`. The package is decomposed into focused, single-responsibility modules:

1. **`models.py`**: Immutable dataclass definitions (`ClusterNode`, `DriftReport`, `ClusterHierarchyResult`).
2. **`scc.py`**: Iterative non-recursive Tarjan's Strongly Connected Components (O(V + E)), immune to Python recursion limits.
3. **`affinity.py`**: Integer index compaction, inverse in-degree hub dampening ($w' = \frac{w_{\text{base}}}{\sqrt{\deg_{\text{in}}}}$ with $1.5\times$ reciprocal bonus), soft `parent_symbol` affinity (1.5), and zero-degree unreferenced symbol isolation.
4. **`aggregator.py`**: Louvain modularity local moving with preserved internal self-loop mass ($A_{\text{internal}}$), dominance-gated hub ejection ($\le 50\%$), private dependency absorption with fan-out guards, and monotonic level recalculation.
5. **`naming.py`**: Plurality and deepest dominant directory heuristics, single-class detection, and top internal hub heuristics.
6. **`metrics.py`**: Unit-consistent node-based containment scoring (`symbol` vs `file` modes), boundary targets, external callers, and deque-based BFS closures.
7. **`drift.py`**: Architectural drift diagnostics (split-brain files and classes evaluated against top-level subsystem boundaries, misplaced symbols, and scattered clusters).
8. **`analyzer.py`**: Ingress filtering and pipeline coordination via `build_cluster_hierarchy()`.

During super-node contraction across passes $L \ge 2$, internal edge mass within contracted super-nodes is accumulated into $A_{\text{internal}}$ and preserved in node degree ($k_i = 2 \cdot A_{\text{internal}}[i] + \sum_{j \ne i} A[i][j]$) and total graph weight $2m$. Aggregation runs in $O(E)$ sparse iterations using a `sym_id_to_supernode` index.

**Reason:** 
1. Splitting clustering into discrete modules enforces separation of concerns between graph normalization, cycle contraction, modularity optimization, and diagnostic reporting.
2. Preserving internal self-loop weights prevents the null model $\frac{k_i k_j}{2m}$ from treating dense cohesive super-nodes as low-degree singletons, eliminating systematic over-merging of unrelated subsystems in passes $L \ge 2$.
3. The $O(E)$ sparse edge pass avoids quadratic $O(N^2)$ pair iteration cliffs, keeping execution under 50ms on 10,000 symbols.

**Rejected alternative (Single-file monolithic engine in `src/engines/`):** Placing all ~1,000 lines into `src/engines/cluster_analyzer.py` was rejected. Clustering is a high-level architectural domain analysis, not an AST or compiler engine like SCIP or Tree-sitter. A single file violated the single-responsibility principle and created unacceptable cognitive load.

**Rejected alternative (Compatibility facade in `src/engines/`):** Introducing an artificial re-export facade in `src/engines/cluster_analyzer.py` was rejected. Layer boundaries should be direct and unambiguous; consumers import directly from `clustering`.

---

## Elimination of synthetic Implements cycles and boundary-aware drift diagnostics

**Id:** a37ae2c7-5add-4f85-a402-b039ce3df3ed
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-24
**Revisit when:** SCIP protocol introduces dedicated runtime dispatch metadata distinct from structural declaration relationships

Two critical fixes were applied to graph construction, Tarjan cycle detection, and drift diagnostics:

1. **Non-cycle Implements Orientation in Tarjan SCC**:
   - `iterative_tarjan_scc` runs strictly over direct call and structural dependency edges (`Calls`, `TypeDefinition`, `Injects`, `FFI_Binds`).
   - `Implements` edges are given strong undirected affinity (weight 2.0) during clustering but are not inverted into synthetic `Interface -> Concrete` edges in the directed cycle-detection graph.
   - *Reason*: Reversing `Concrete --[Implements]--> Interface` to `Interface -> Concrete` while standard `Calls` edges existed created artificial 2-cycles (`Concrete <-> Interface`) that fused interfaces and all implementations into irreversible Level-0 cycle blobs before Louvain or Dominance Gate could separate them.
2. **Subsystem-Relative Drift Purity**:
   - `split_files` and `split_classes` evaluate purity against top-level subsystem boundaries rather than finest leaf clusters.
   - *Reason*: Evaluating purity strictly against leaf clusters produced false-positive storms on cohesive classes or files that naturally decompose into sibling sub-clusters (e.g. `c1.1`, `c1.2`) under the same parent subsystem.
3. **Ingress Peer Endpoint Sanitization**:
   - Boundary targets and callers are filtered against boilerplate, excluded paths, and test files (`is_auxiliary_path`, `is_test_caller`) when `include_tests=False`.
   - *Reason*: Unfiltered external peer edges previously inflated incident degree counts, causing dead production symbols called only by test suites to falsely exit `unreferenced_symbols`.
