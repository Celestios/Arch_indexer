# DuckDB Resilience and WAL Recovery

## Automatic quarantine and recovery for unreplayable DuckDB WAL assertion failures

**Id:** 5d35899d-0e00-4435-b63b-a35894fca92c
**Type:** workaround
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** developer incident and architecture decision, 2026-11-17
**Revisit when:** DuckDB fixes WAL replay assertion failures for default database contexts in upstream releases (issues #19712 and #21490)

In `DbConnection.get_connection()`, startup connection errors matching DuckDB internal assertion failures during WAL replay (`Failure while replaying WAL file: Calling DatabaseManager::GetDefaultDatabase with no default database set`) are caught automatically. The unreplayable WAL file is renamed and quarantined to `<dbname>.wal.corrupt`, and a clean connection to the checkpointed primary database file is re-established.

**Reason:** When DuckDB terminates abruptly while write transactions with default expressions are un-checkpointed, restarting DuckDB triggers an internal assertion failure during WAL replay because the default database manager context is not yet initialized. Because DuckDB provides no partial WAL replay mode or skip-corrupt flag, the database is completely locked out from all MCP tools and CLI commands. In Arch MCP, the database is a derived index of the codebase (source of truth is the code files, SCIP indexes, and config.json). Quarantining the unreplayable WAL allows DuckDB to immediately open the intact checkpointed database (preserving all previous files, symbols, and violations), while any un-checkpointed delta can be reconciled in seconds via `reindex` or `audit`.

**Rejected alternative:** Requiring the user to delete the entire `.arch/arch.db` database and reindex from scratch was rejected because it would destroy manual classification fields, justifications, and audit statuses when only the recent uncheckpointed write log was invalid. Silently unlinking/deleting the WAL file was rejected because quarantining it preserves the raw transaction bytes for diagnostics and forensics.

---

## DuckDB CSV staging via native C++ read_csv and linear semi-join edge deletions

**Id:** 640ac377-9ee4-4dad-ba35-330785dda1a9
**Type:** decision
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** performance profiling and architecture decision, 2026-11-23
**Revisit when:** DuckDB Python client provides zero-copy Apache Arrow / columnar buffer binding in PyInstaller bundles without external dependencies

Bulk persistence in `src/db/store_graph.py` was refactored from `SELECT UNNEST(?::TYPE[])` and `cursor.executemany` to streaming data into temporary CSV files via `_csv_staging` in `BaseRepository`, loaded via DuckDB's native C++ `read_csv()` into unindexed staging tables with explicit `columns={...}`, `delim=','`, `quote='"'`, `escape='"'`, `nullstr=''`. Set-based `UPDATE ... FROM _stg` and `INSERT INTO ... SELECT DISTINCT ON ... WHERE NOT EXISTS` apply the batches. In addition, the dead-weight secondary ART index `idx_symbols_clean_symbol` on `symbols(clean_symbol)` was dropped, and `delete_edges` was refactored to materialize target symbols in a temp table and perform two linear single-column semi-joins instead of an `OR` across nested subqueries.

**Reason:** In DuckDB, `cursor.executemany` does not perform columnar batch insertion; it executes row-by-row interpreted SQL against ART primary key indexes, stalling writes at scale. While parameterized `SELECT UNNEST(?::TYPE[])` avoided row-by-row SQL interpretation, passing 10,000-element Python lists across 13 columns forced `duckdb-python` to box ~130,000 Python objects per chunk into C++ heap `duckdb::Value::LIST` instances, causing hundreds of megabytes of memory churn and taking ~60 seconds per 20,000 rows. DuckDB's C++ `read_csv()` bypasses Python object boxing entirely, loading and deduplicating 50,000 edges and 100,000 occurrences in 0.40 seconds (a 150x-400x speedup). Explicit column definitions in `read_csv` disable the sniffer, preventing type-inference failures on complex docstrings. In `delete_edges`, combining two nested `IN (SELECT ... UNNEST)` subqueries with `OR` prevented DuckDB from compiling hash semi-joins, triggering expensive MARK joins and memory buffer exhaustion.

**Rejected alternative (PyArrow table registration):** While PyArrow provides in-memory zero-copy table registration, PyArrow is an external C++ dependency with a large binary footprint (>150MB) that is not bundled into the standalone Windows PyInstaller distribution. `read_csv()` achieves identical performance using standard Python library `csv`/`tempfile` and DuckDB's built-in CSV parser with zero external dependencies.

**Rejected alternative (smaller UNNEST chunk sizes):** Reducing UNNEST chunk sizes from 10,000 to 1,000 reduced peak memory per chunk but retained the steep per-element boxing overhead and repeated SQL compilation cost, remaining orders of magnitude slower than native CSV bulk loading.
