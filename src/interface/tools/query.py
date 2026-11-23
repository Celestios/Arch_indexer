import json
import datetime
from pathlib import Path
from typing import Optional, Any, Dict, List
import duckdb


def _json_serial(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return str(obj)


ALLOWED_STATEMENT_TYPES = {
    duckdb.StatementType.SELECT,
    duckdb.StatementType.EXPLAIN,
    duckdb.StatementType.PRAGMA,
}


def handle_query(
    repository,
    project_root: Path,
    sql: str,
    limit: Optional[int] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    Executes a read-only SQL query against the repository DuckDB database.
    If output_path is provided, exports entire results to a JSON file.
    Otherwise, returns structured JSON string with optional row truncation.
    """
    cleaned_sql = (sql or "").strip()
    if not cleaned_sql:
        return "Error: SQL query cannot be empty."

    with repository._db_conn.session() as conn:
        # Validate read-only nature via DuckDB's native parser
        try:
            statements = conn.extract_statements(cleaned_sql)
        except Exception as e:
            return f"SQL Parse Error: {e}"

        if not statements:
            return "Error: No executable SQL statement found."

        for stmt in statements:
            if stmt.type not in ALLOWED_STATEMENT_TYPES:
                return (
                    f"Forbidden statement type: {stmt.type.name}. "
                    "Only read-only queries (SELECT, WITH, EXPLAIN, PRAGMA, DESCRIBE, SHOW) are permitted."
                )

        try:
            rel = conn.execute(cleaned_sql)
            columns: List[str] = [desc[0] for desc in rel.description] if rel.description else []
            rows: List[tuple] = rel.fetchall()
        except Exception as e:
            return f"SQL Execution Error: {e}"

    total_rows = len(rows)

    if output_path:
        out_path = Path(output_path)
        if not out_path.is_absolute():
            out_path = (project_root / out_path).resolve()

        export_rows = rows[:limit] if (limit is not None and limit > 0) else rows
        records = [dict(zip(columns, row)) for row in export_rows]

        payload = {
            "sql": cleaned_sql,
            "columns": columns,
            "total_rows": total_rows,
            "exported_rows": len(records),
            "data": records,
        }

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=_json_serial)
        except Exception as e:
            return f"Error writing query results to file '{out_path}': {e}"

        file_size = out_path.stat().st_size
        preview_count = min(3, len(records))
        preview = records[:preview_count]

        summary = [
            f"### Query Executed Successfully",
            f"- **Destination**: `{out_path}`",
            f"- **Exported Rows**: {len(records)} (Total rows: {total_rows})",
            f"- **Columns**: `{', '.join(columns)}`",
            f"- **File Size**: {file_size:,} bytes",
        ]
        if preview:
            summary.append(f"\n**Preview (first {preview_count} rows):**")
            summary.append("```json")
            summary.append(json.dumps(preview, indent=2, default=_json_serial))
            summary.append("```")

        return "\n".join(summary)

    # In-memory return
    effective_limit = limit if (limit is not None and limit > 0) else 100
    is_truncated = total_rows > effective_limit
    selected_rows = rows[:effective_limit]
    records = [dict(zip(columns, row)) for row in selected_rows]

    result: Dict[str, Any] = {
        "columns": columns,
        "row_count": len(records),
        "total_rows": total_rows,
        "truncated": is_truncated,
        "rows": records,
    }
    if is_truncated:
        result["hint"] = (
            f"Showing first {effective_limit} of {total_rows} rows. "
            "Pass output_path='filename.json' to save full result to disk, or pass limit=N."
        )

    return json.dumps(result, indent=2, default=_json_serial)
