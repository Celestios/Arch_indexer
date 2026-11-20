import json
from typing import Dict, List, Any, Optional, Union, Tuple
from collections import defaultdict

from utils.helpers import demangle_scip_symbol


def _normalize_target(t: Dict[str, Any], default_ext: bool = False) -> Dict[str, Any]:
    raw_path = t.get("path", "")
    if raw_path in (".", "./", "/"):
        path = ""
    else:
        path = raw_path.replace("\\", "/").strip("/")

    tree_depth = int(t.get("tree_depth", 1))
    detail_raw = t.get("detail_level", "folder")
    if isinstance(detail_raw, int):
        int_map = {1: "folder", 2: "folder", 3: "file", 4: "class", 5: "symbol"}
        detail_level = int_map.get(detail_raw, "folder")
    else:
        detail_level = str(detail_raw).lower()
        if detail_level not in ("folder", "file", "class", "symbol"):
            detail_level = "folder"

    include_external = bool(t.get("include_external", default_ext))
    return {
        "path": path,
        "tree_depth": tree_depth,
        "detail_level": detail_level,
        "include_external": include_external,
    }


def _matches_target(fp: Optional[str], target_path: str, include_external: bool) -> bool:
    if not fp:
        return include_external or target_path == "external"
    norm_fp = fp.replace("\\", "/").strip("/")
    if not target_path:
        return True
    return norm_fp == target_path or norm_fp.startswith(target_path + "/")


def _compute_group_name(
    fp: Optional[str],
    sym_info: Dict[str, Any],
    target_path: str,
    tree_depth: int,
    detail_level: str,
) -> str:
    if not fp:
        return "external/"

    norm_fp = fp.replace("\\", "/").strip("/")

    if detail_level == "symbol":
        clean = sym_info.get("clean_symbol") or demangle_scip_symbol(sym_info.get("symbol", ""))
        return clean or sym_info.get("symbol", "unknown")

    if detail_level == "class":
        parent = sym_info.get("parent_symbol")
        if parent:
            return demangle_scip_symbol(parent)
        kind = (sym_info.get("kind") or "").lower()
        if kind in ("class", "struct", "interface") or sym_info.get("symbol", "").endswith("#"):
            return demangle_scip_symbol(sym_info.get("symbol", ""))
        return norm_fp

    if detail_level == "file":
        return norm_fp

    # Default: "folder"
    if target_path and norm_fp.startswith(target_path + "/"):
        rel = norm_fp[len(target_path) + 1 :]
        base = target_path + "/"
    elif target_path and norm_fp == target_path:
        rel = ""
        base = target_path + "/"
    elif not target_path:
        rel = norm_fp
        base = ""
    else:
        rel = norm_fp
        base = ""

    parts = [p for p in rel.split("/") if p]
    dir_parts = parts[:-1]  # Exclude filename

    if tree_depth == 0:
        return (target_path + "/") if target_path else "./"
    if not dir_parts:
        return base if base else "./"
    if len(dir_parts) <= tree_depth:
        return base + "/".join(dir_parts) + "/"
    return base + "/".join(dir_parts[:tree_depth]) + "/"


def handle_map(
    repository,
    targets: Optional[Union[List[Dict[str, Any]], str]] = None,
    path: str = "",
    tree_depth: int = 1,
    detail_level: str = "folder",
    include_external: bool = False,
) -> str:
    """
    Provides a structured, hierarchical architectural blueprint map of the repository.
    Use this tool when exploring an unfamiliar codebase, understanding subsystem boundaries and topologies, discovering inter-module call dependencies, identifying central architectural hubs, or surveying code organization at configurable depths.
    """
    # 1. Parse and normalize target queries
    parsed_targets: List[Dict[str, Any]] = []
    if isinstance(targets, str):
        try:
            loaded = json.loads(targets)
            if isinstance(loaded, list):
                parsed_targets = [_normalize_target(t, default_ext=include_external) for t in loaded]
            elif isinstance(loaded, dict):
                parsed_targets = [_normalize_target(loaded, default_ext=include_external)]
        except Exception:
            parsed_targets = []
    elif isinstance(targets, list):
        parsed_targets = [_normalize_target(t, default_ext=include_external) for t in targets]
    elif isinstance(targets, dict):
        parsed_targets = [_normalize_target(targets, default_ext=include_external)]

    if not parsed_targets:
        parsed_targets = [
            _normalize_target(
                {
                    "path": path,
                    "tree_depth": tree_depth,
                    "detail_level": detail_level,
                    "include_external": include_external,
                },
                default_ext=include_external,
            )
        ]

    # Global external flag: true if any target requests external symbols
    global_allow_ext = any(t["include_external"] for t in parsed_targets)

    # 2. Fetch repository totals & raw entities
    totals = repository.analytics.get_repo_totals()

    with repository.db_conn.session() as conn:
        sym_rows = conn.execute(
            "SELECT symbol, clean_symbol, filepath, kind, signature, parent_symbol FROM symbols"
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT source, target, weight FROM edges"
        ).fetchall()

    symbols_dict: Dict[str, Dict[str, Any]] = {}
    for r in sym_rows:
        sym_id = r[0]
        symbols_dict[sym_id] = {
            "symbol": sym_id,
            "clean_symbol": r[1],
            "filepath": r[2],
            "kind": r[3],
            "signature": r[4],
            "parent_symbol": r[5],
        }

    # 3. Compute degree and call weights per symbol
    in_degrees: Dict[str, int] = defaultdict(int)
    out_degrees: Dict[str, int] = defaultdict(int)
    for src, tgt, weight in edge_rows:
        if not global_allow_ext:
            src_fp = symbols_dict.get(src, {}).get("filepath")
            tgt_fp = symbols_dict.get(tgt, {}).get("filepath")
            if not src_fp or not tgt_fp:
                continue
        w = int(weight) if weight else 1
        out_degrees[src] += w
        in_degrees[tgt] += w

    # 4. Map symbols to target queries & groups
    symbol_to_group: Dict[str, str] = {}
    groups: Dict[str, Dict[str, Any]] = {}

    for t_idx, tgt in enumerate(parsed_targets):
        t_path = tgt["path"]
        t_depth = tgt["tree_depth"]
        t_detail = tgt["detail_level"]
        t_ext = tgt["include_external"]

        for sym_id, s in symbols_dict.items():
            if sym_id in symbol_to_group:
                continue  # First matching target wins
            fp = s.get("filepath")
            if _matches_target(fp, t_path, t_ext):
                grp_name = _compute_group_name(fp, s, t_path, t_depth, t_detail)
                symbol_to_group[sym_id] = grp_name
                if grp_name not in groups:
                    groups[grp_name] = {
                        "name": grp_name,
                        "target_idx": t_idx,
                        "detail_level": t_detail,
                        "filepaths": set(),
                        "symbols": [],
                    }
                if fp:
                    groups[grp_name]["filepaths"].add(fp)
                groups[grp_name]["symbols"].append(s)

    # 5. Compute in/out calls between groups
    group_inbound: Dict[str, int] = defaultdict(int)
    group_outbound: Dict[str, int] = defaultdict(int)
    inter_group_calls: Dict[Tuple[str, str], int] = defaultdict(int)

    for src, tgt, weight in edge_rows:
        src_grp = symbol_to_group.get(src)
        tgt_grp = symbol_to_group.get(tgt)
        if not src_grp or not tgt_grp:
            continue
        if src_grp != tgt_grp:
            w = int(weight) if weight else 1
            group_outbound[src_grp] += w
            group_inbound[tgt_grp] += w
            inter_group_calls[(src_grp, tgt_grp)] += w

    # 6. Build Markdown Output
    md: List[str] = ["## Repository Architectural Blueprint Map\n"]

    # Section A: Totals
    md.append("### Project Totals")
    md.append("| Files Indexed | Symbols Registered | Dependencies (Call Graph) | Active Violations |")
    md.append("| :---: | :---: | :---: | :---: |")
    md.append(
        f"| {totals.get('files', 0)} | {totals.get('symbols', 0)} | "
        f"{totals.get('edges', 0)} | {totals.get('violations', 0)} |\n"
    )

    # Section B: Target Tables
    for t_idx, tgt in enumerate(parsed_targets):
        t_path = tgt["path"]
        t_depth = tgt["tree_depth"]
        t_detail = tgt["detail_level"]
        path_label = f"`{t_path}/`" if t_path else "`./` (Root)"
        header_title = f"Architecture Nodes ({path_label}, tree_depth={t_depth}, detail=\"{t_detail}\")"

        tgt_groups = [g for g in groups.values() if g["target_idx"] == t_idx]
        tgt_groups.sort(key=lambda x: len(x["symbols"]), reverse=True)

        md.append(f"### {header_title}")
        if not tgt_groups:
            md.append("*No symbols matched this target query.*\n")
            continue

        if t_detail == "folder":
            md.append("| Module / Subsystem | Files | Symbols | Inbound | Outbound | Top Hub Symbol (Connections) |")
            md.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
            for g in tgt_groups:
                g_syms = g["symbols"]
                top_sym = max(g_syms, key=lambda s: in_degrees[s["symbol"]] + out_degrees[s["symbol"]])
                deg = in_degrees[top_sym["symbol"]] + out_degrees[top_sym["symbol"]]
                hub_label = top_sym.get("clean_symbol") or demangle_scip_symbol(top_sym["symbol"]) or top_sym["symbol"]
                hub_display = f"`{hub_label}` ({deg})" if deg > 0 else f"`{hub_label}`"
                in_c = group_inbound[g["name"]]
                out_c = group_outbound[g["name"]]
                md.append(f"| `{g['name']}` | {len(g['filepaths'])} | {len(g_syms)} | {in_c} | {out_c} | {hub_display} |")

        elif t_detail == "file":
            md.append("| File | Symbols | Inbound | Outbound | Top Hub Symbol (Connections) |")
            md.append("| :--- | :---: | :---: | :---: | :--- |")
            for g in tgt_groups:
                g_syms = g["symbols"]
                top_sym = max(g_syms, key=lambda s: in_degrees[s["symbol"]] + out_degrees[s["symbol"]])
                deg = in_degrees[top_sym["symbol"]] + out_degrees[top_sym["symbol"]]
                hub_label = top_sym.get("clean_symbol") or demangle_scip_symbol(top_sym["symbol"]) or top_sym["symbol"]
                hub_display = f"`{hub_label}` ({deg})" if deg > 0 else f"`{hub_label}`"
                in_c = group_inbound[g["name"]]
                out_c = group_outbound[g["name"]]
                md.append(f"| `{g['name']}` | {len(g_syms)} | {in_c} | {out_c} | {hub_display} |")

        elif t_detail == "class":
            md.append("| Component / Class | Kind | File | Symbols | Inbound | Outbound | Top Hub Symbol |")
            md.append("| :--- | :--- | :--- | :---: | :---: | :---: | :--- |")
            for g in tgt_groups:
                g_syms = g["symbols"]
                top_sym = max(g_syms, key=lambda s: in_degrees[s["symbol"]] + out_degrees[s["symbol"]])
                deg = in_degrees[top_sym["symbol"]] + out_degrees[top_sym["symbol"]]
                hub_label = top_sym.get("clean_symbol") or demangle_scip_symbol(top_sym["symbol"]) or top_sym["symbol"]
                hub_display = f"`{hub_label}` ({deg})" if deg > 0 else f"`{hub_label}`"
                first_fp = next(iter(g["filepaths"]), "-")
                first_kind = top_sym.get("kind", "Class")
                in_c = group_inbound[g["name"]]
                out_c = group_outbound[g["name"]]
                md.append(f"| `{g['name']}` | {first_kind} | `{first_fp}` | {len(g_syms)} | {in_c} | {out_c} | {hub_display} |")

        elif t_detail == "symbol":
            md.append("| Symbol | Kind | File | Inbound | Outbound | Signature |")
            md.append("| :--- | :--- | :--- | :---: | :---: | :--- |")
            limit = 50
            display_syms = sorted(
                tgt_groups,
                key=lambda g: in_degrees[g["symbols"][0]["symbol"]] + out_degrees[g["symbols"][0]["symbol"]],
                reverse=True,
            )
            for g in display_syms[:limit]:
                s = g["symbols"][0]
                sid = s["symbol"]
                s_fp = s.get("filepath") or "-"
                s_kind = s.get("kind") or "-"
                s_sig = s.get("signature") or "-"
                if len(s_sig) > 40:
                    s_sig = s_sig[:37] + "..."
                in_c = in_degrees[sid]
                out_c = out_degrees[sid]
                md.append(f"| `{g['name']}` | {s_kind} | `{s_fp}` | {in_c} | {out_c} | `{s_sig}` |")
            if len(display_syms) > limit:
                md.append(f"\n*(Showing top {limit} of {len(display_syms)} symbols sorted by connections)*")

        md.append("")

    # Section C: Inter-Module Call Dependencies (Directional arrows)
    md.append("### Inter-Module Call Dependencies")
    if not inter_group_calls:
        md.append("*No inter-module dependencies detected for the specified target(s).*\n")
    else:
        sorted_calls = sorted(inter_group_calls.items(), key=lambda x: x[1], reverse=True)
        for (src_g, tgt_g), call_count in sorted_calls:
            calls_plural = "call" if call_count == 1 else "calls"
            md.append(f"- `{src_g}` ──[{call_count} {calls_plural}]──> `{tgt_g}`")
        md.append("")

    return "\n".join(md)
