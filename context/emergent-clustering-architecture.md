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

---

## Direction-aware Louvain aggregation with dampened coupling scale and zero-edge container promotion

**Id:** 91f4b80b-dfb3-463d-88b9-87a3e742c382
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision and audit review, 2026-11-24
**Revisit when:** community detection graph algorithms natively support multi-layer directed multiplex networks without loss of modularity scale

Clustering aggregation was refactored to eliminate artificial numeric connectivity cutoffs (`w_total >= 3.0`, `deg >= 3`, `ext >= 3`) and resolve mathematical scale mismatches:

1. **Unified Dampened Affinity Scale Across All Phases**:
   - Louvain (Phase A), Dominance Gate (Phase B), and Private Dependency Absorption (Phase C) all evaluate the exact same dampened directed and undirected weights ($w / \sqrt{\deg_{\text{in}}}$).
   - Removed un-dampened raw coupling checks (`raw_dep_weight`), which previously caused normal classes calling high-degree utilities (e.g. `Logger`, `GraphNode`) to miscalculate external coupling and prematurely eject methods to root.
2. **Direction-Aware Hub and Orchestrator Ejection (Phase B)**:
   - Fixed off-by-one community count check: Evaluates strictly external communities (`connected_comms - {c_u} >= 2`), preventing ordinary 1-to-1 boundary methods from being misclassified as cross-cutting hubs.
   - Symmetrically classifies two valid topological hub types:
     * *Inbound Shared Hub*: Inbound callers span $\ge 2$ external communities with internal dampened share $\le 50\%$.
     * *Callerless Orchestrator*: Zero inbound callers (`in_deg == 0`), outbound dependencies span $\ge 2$ external communities, with internal dampened share $\le 50\%$.
   - Outbound consumers (commands, controllers) that call downstream services are no longer conflated with shared hubs.
3. **Zero-Edge Container Promotion & Vertical Class-Method Cohesion (`affinity.py`)**:
   - `parent_symbol` affinity weight was increased to 2.0 (strictly undirected in `undirected_aff`, omitted from `dir_out_edges` so Tarjan SCC cannot synthesize artificial cycles).
   - Containers (classes, structs) with zero direct incident edges whose member methods have dependencies are promoted into `clustered_symbols` before unreferenced partitioning. This prevents container types from being exiled to unreferenced while their methods cluster in isolation.
4. **Topological LCA Singleton Partitioning**:
   - Root singletons are partitioned without numeric thresholds:
     * *Shared Hub*: Couples to $\ge 2$ distinct sibling root clusters.
     * *Residual*: Couples to $\le 1$ sibling root cluster.
   - Sorts hubs by coupled sibling count and incident degree.

**Reason:** Replacing arbitrary numeric thresholds with topological invariants produces stable, scale-free emergent clusters across small and large codebases (tested up to 20,000+ symbols in Centrode). Methods remain naturally bonded to their classes without hard-locking God Classes, and singleton spam is eliminated.

**Rejected alternative (Arbitrary connectivity floors like `deg >= 3` or `w_total >= 3.0`):** Adding arbitrary degree or weight cutoffs masked structural bugs in Phase B's community counting and dampened-vs-undampened scale mismatch, but produced brittle, language-dependent clustering that failed on lightly coupled or clean modular code.

---

## Post-clustering Instability, Macro Quotient Cycles, and Closure diagnostics

**Id:** 32fd4dba-e429-4115-8b4e-cb4844e6e9d0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-25
**Revisit when:** `clusters` integrates optional `.arch/config.json` layer-rule annotations or DuckDB materializes quotient-graph metrics natively

Moving shared code out to a lower layer (e.g., `features/graph/` to `lib/shared/`) turns internal calls into external dependencies (`Ext Deps`), which lowers raw `containment_pct` even when the refactor eliminates a dependency cycle and produces a clean acyclic DAG. Raw containment alone cannot distinguish healthy downward fan-out from cyclic subsystem coupling, and `is_cycle` (Level-0 Tarjan SCC) misses macro cycles formed by non-overlapping symbol pairs across modules (`c1::a -> c2::b` and `c2::c -> c1::d`).

To surface architectural directionality without altering Louvain clustering (`affinity.py`, `aggregator.py`, `analyzer.py`), four orthogonal post-clustering fields were added to `ClusterNode` (`models.py`), computed in `metrics.py`, and surfaced across all four `clusters` views (`summary`, `tree`, `mermaid`, and leaf zoom):
- **Instability (`I`)**: $C_e / (C_a + C_e) \in [0.0, 1.0]$ (`0.0` when $C_a + C_e = 0$).
- **Macro Quotient Cycles**: `compute_quotient_cycles()` projects `ext_deps_by_cluster` onto sibling/frontier nodes and runs `iterative_tarjan_scc()` recursively at every hierarchy level, populating `internal_macro_cycles`, `macro_cycle_peers`, and `cyclic_ext_dep_count` while keeping `is_cycle` strictly scoped to Level-0 atomic symbol SCCs (`[local-cycle]`).
- **Transitive Closure Amplification**: `summary` pairs `Ext (Closure)` directly so wide transitive cones are visible alongside direct boundary edges.

**Reason:** Separating post-clustering diagnostics from graph aggregation preserves parameter-free clustering stability while exposing DAG directionality, DIP sink stability (`I = 0.0`), and subsystem-level cycles at every zoom depth.

**Rejected alternative (Overloading `is_cycle` for both symbol SCCs and macro subsystem cycles):** Conflating atomic symbol cycles with boundary cycles between acyclic leaves obscures whether a cycle is local to a few symbols or spans module boundaries.

**Rejected alternative (Layer-aware containment scoring inside `clusters`):** Importing `.arch/config.json` boundary rules into `clusters` was rejected to keep emergent clustering rule-independent; explicit layer compliance remains the responsibility of `audit`.
