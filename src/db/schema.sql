-- Schema for Arch-mcp code intelligence database (DuckDB)

-- 1. Track files in the workspace, their hashes, and when they were indexed
CREATE TABLE IF NOT EXISTS files (
    filepath VARCHAR PRIMARY KEY,
    sha256 VARCHAR NOT NULL,
    language VARCHAR NOT NULL,
    last_indexed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR NOT NULL DEFAULT 'COMPLIANT', -- 'COMPLIANT' or 'VIOLATION_DETECTED'
    manual_status VARCHAR NOT NULL DEFAULT 'COMPLIANT', -- 'COMPLIANT' or 'VIOLATION_DETECTED'
    pending_audit BOOLEAN NOT NULL DEFAULT TRUE,
    manual_fields VARCHAR NOT NULL DEFAULT '{}', -- JSON string containing manual metadata fields
    justification TEXT
);

-- 2. Track symbols (classes, functions, methods, structs)
CREATE TABLE IF NOT EXISTS symbols (
    symbol VARCHAR PRIMARY KEY,
    filepath VARCHAR, -- Nullable for external third-party library dependencies
    kind VARCHAR NOT NULL, -- Class, Struct, Function, Method, etc.
    signature TEXT,
    docstring TEXT,
    body_hash VARCHAR, -- AST body hash to skip edge update if unchanged
    connection_weight INTEGER DEFAULT 0
);

-- 3. Track physical locations where symbols are referenced/defined
CREATE TABLE IF NOT EXISTS occurrences (
    symbol VARCHAR,
    filepath VARCHAR,
    start_line INTEGER NOT NULL,
    start_col INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    end_col INTEGER NOT NULL,
    role INTEGER NOT NULL -- Bitmask representation: Definition = 1, Reference = 2, etc.
);

-- 4. Track dependency, inheritance, and call graph relations between symbols
CREATE TABLE IF NOT EXISTS edges (
    source VARCHAR,
    target VARCHAR,
    relation VARCHAR NOT NULL, -- e.g., 'Calls', 'Inherits', 'Implements'
    weight FLOAT NOT NULL DEFAULT 1.0,
    PRIMARY KEY (source, target, relation)
);

-- 5. Track compliance rules loaded from configuration templates
CREATE TABLE IF NOT EXISTS compliance_rules (
    rule_id VARCHAR PRIMARY KEY,
    description TEXT NOT NULL,
    severity VARCHAR NOT NULL -- e.g., 'Error', 'Warning', 'Info'
);

-- 6. Track violations discovered during compliance audits
CREATE TABLE IF NOT EXISTS compliance_violations (
    violation_id VARCHAR PRIMARY KEY,
    rule_id VARCHAR,
    symbol VARCHAR,
    filepath VARCHAR NOT NULL,
    line INTEGER NOT NULL,
    message TEXT NOT NULL,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    origin VARCHAR DEFAULT 'automatic' -- 'automatic' or 'manual'
);

-- 7. Track system metadata (e.g. config hashes, indexing state)
CREATE TABLE IF NOT EXISTS system_metadata (
    key VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);
