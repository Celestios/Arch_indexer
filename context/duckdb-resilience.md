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
