from engines.communities import detect_communities


def handle_map(repository) -> str:
    """Provide a high-level architectural map. Returns markdown."""
    totals = repository.metrics.get_repo_totals()
    communities, connections, degrees = detect_communities(repository)

    md = ["## Repository Architectural Blueprint Map\n"]

    md.append("### Project Totals")
    md.append(f"- **Files Indexed**: {totals['files']}")
    md.append(f"- **Symbols Registered**: {totals['symbols']}")
    md.append(f"- **Dependencies (Call Graph Edges)**: {totals['edges']}")
    md.append(f"- **Active Architectural Violations**: {totals['violations']}")
    md.append("")

    md.append("### Detected Architectural Communities")
    if not communities:
        md.append("*No communities detected (empty database).*")
    else:
        sorted_comms = sorted(communities.items(), key=lambda x: len(x[1]), reverse=True)
        for comm_name, syms in sorted_comms:
            md.append(f"#### Community: `{comm_name}` ({len(syms)} symbol(s))")
            comm_syms_sorted = sorted(syms, key=lambda x: degrees.get(x, 0), reverse=True)
            top_hubs = comm_syms_sorted[:3]
            md.append("  - **Key Hub Symbols**:")
            for hub in top_hubs:
                md.append(f"    * `{hub}` (Connections: {degrees.get(hub, 0)})")
            md.append("")

    md.append("### Inter-Community Call Dependencies")
    has_connections = False
    if connections:
        for src_comm, tgts in sorted(connections.items()):
            for tgt_comm, weight in sorted(tgts.items(), key=lambda x: x[1], reverse=True):
                md.append(f"- `{src_comm}` ──[{weight} call(s)]──> `{tgt_comm}`")
                has_connections = True
    if not has_connections:
        md.append("*No inter-community dependencies found.*")
    md.append("")

    return "\n".join(md)
