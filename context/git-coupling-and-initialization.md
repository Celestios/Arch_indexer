# Git Coupling and Workspace Initialization

## Disabling historical git co-change ingestion due to non-atomic commit pollution

**Id:** 7b420e62-c1f9-4d2b-b65f-4a0b5f6311e9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer architecture decision, 2026-11-18
**Revisit when:** A semantic, graph-validated or hunk-level co-change mining heuristic is implemented and vetted

Historical git co-change mining (`GitCouplingMiner.mine_git_co_changes()`) was disabled in `src/setup/initializer.py`.

**Reason:** The miner parses the last 500 git commits and computes Cartesian pairwise combinations ($O(N^2)$) of all files modified in each commit. In real-world repositories with non-atomic commits (bulk reformatting, license updates, dependency lockfile bumps, or monorepo merge commits), this created massive false-positive correlations between completely unrelated files and bloated `arch.db` with hundreds of thousands of spurious rows (e.g., 356k rows taking ~54MB). Simple file-count heuristics fail because they cause both false positives (small non-atomic commits) and false negatives (valid large atomic refactors). Mining is paused until an opt-in or graph-correlated approach is developed.

**Rejected alternative (Hardcoded commit file-size caps):** Discarding commits with $>50$ files was rejected because it introduces arbitrary thresholds that fail to distinguish true cross-cutting atomic changes from non-atomic commits.

---

## Idempotent directory selection in workspace initialization

**Id:** 3a921d7b-e104-4c47-9f79-2d12e8b0a993
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer session, 2026-11-18
**Revisit when:** Workspace configuration moves to an interactive TUI wizard

`arch init` checks `.arch/config.json` before prompting for directories to index. If valid directory rules already exist and `--force` is not set, `_select_include_dirs()` reuses the existing configuration without prompting. When prompted on new repositories, choices are persisted directly to `config.json`.

**Reason:** Previously, `_select_include_dirs()` prompted interactively on every execution regardless of whether `config.json` was already initialized. Because `initialize_workspace()` created `config.json` before the prompt ran, the interactive selection was discarded and never written to the configuration.
