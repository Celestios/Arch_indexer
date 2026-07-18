def handle_impact(symbol: str, max_depth: int, repository) -> str:
    """Blast radius analysis for a symbol. Returns markdown."""
    closure = repository.edges.get_transitive_closure(symbol, max_depth=max_depth)

    upstream = closure.get("upstream", [])
    downstream = closure.get("downstream", [])

    md = [f"## Blast Radius for: `{symbol}`\n"]

    md.append("### ── Upstream Callers (Who calls this?)")
    if not upstream:
        md.append("*No transitive upstream callers found.*")
    else:
        upstream_sorted = sorted(upstream, key=lambda x: x["depth"])
        for item in upstream_sorted:
            path_str = " ──> ".join(f"`{s.split('.')[-1]}`" for s in item["path"])
            md.append(f"- **{item['symbol']}** [Depth: {item['depth']}]")
            md.append(f"  * Path: {path_str}")
    md.append("")

    md.append("### ── Downstream Callees (What does this call?)")
    if not downstream:
        md.append("*No transitive downstream callees found.*")
    else:
        downstream_sorted = sorted(downstream, key=lambda x: x["depth"])
        for item in downstream_sorted:
            path_str = " ──> ".join(f"`{s.split('.')[-1]}`" for s in item["path"])
            md.append(f"- **{item['symbol']}** [Depth: {item['depth']}]")
            md.append(f"  * Path: {path_str}")
    md.append("")

    return "\n".join(md)
