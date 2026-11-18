"""
Dynamic Hierarchical Funnel & Topological Subsystem Classifier.
Walks the directory tree from root (left, narrow) to leaf subfolders (right, wide),
creating columns per depth level and zones per folder while sorting siblings by call-flow ratio.
"""

import os
from typing import Dict, List, Any, Optional, Union, Set
from pathlib import Path
from ..domain.types import ZONE_PALETTE


class TopologicalZoneClassifier:
    """
    Constructs a hierarchical directory tree from workspace filepaths.
    Root files at the base scope are placed without a zone enclosure in Column 0;
    subfolders expand rightward into columns (depth 1..N) with full zone enclosures.
    """

    @staticmethod
    def _normalize_rel_parts(
        filepath: str,
        scope: Optional[Union[str, List[str], Set[str]]] = None,
        project_root: Optional[Union[str, Path]] = None,
    ) -> List[str]:
        clean = filepath.replace("\\", "/").strip("/")
        if project_root:
            try:
                clean = str(Path(clean).relative_to(project_root)).replace("\\", "/").strip("/")
            except Exception:
                pass

        scopes = []
        if isinstance(scope, (list, set, tuple)):
            scopes = [s.replace("\\", "/").strip("/") for s in scope if s]
        elif isinstance(scope, str) and scope:
            scopes = [s.strip().replace("\\", "/").strip("/") for s in scope.split(",") if s.strip()]

        for s in scopes:
            if clean.startswith(s + "/"):
                clean = clean[len(s) + 1 :]
                break

        parts = [p for p in clean.split("/") if p]
        # Strip common single top-level wrapper if no explicit scope stripped it
        if not scopes and len(parts) >= 2 and parts[0] in ("src", "lib", "app", "pkg", "packages"):
            parts = parts[1:]
        return parts

    @classmethod
    def build_directory_funnel(
        cls,
        packages_dict: Dict[str, Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        links: List[Dict[str, Any]],
        scope: Optional[Union[str, List[str], Set[str]]] = None,
        project_root: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Builds a recursive directory tree where each folder node holds:
        - dir_path: relative path key
        - name: folder display name
        - depth: column index (0 = root files, 1 = first-level folders, etc.)
        - files: direct files inside this folder
        - children: child folder tree nodes (placed in column depth + 1)
        """
        node_by_id = {n["id"]: n for n in nodes}

        # Map each file to its relative directory path and depth
        file_to_dir: Dict[str, str] = {}
        dir_nodes: Dict[str, Dict[str, Any]] = {
            "": {
                "dir_path": "",
                "name": "ROOT",
                "depth": 0,
                "parent_path": None,
                "files": [],
                "children_paths": set(),
            }
        }

        for fp in packages_dict.keys():
            parts = cls._normalize_rel_parts(fp, scope=scope, project_root=project_root)
            if len(parts) <= 1:
                file_to_dir[fp] = ""
                dir_nodes[""]["files"].append(fp)
            else:
                dir_parts = parts[:-1]
                cur_path = ""
                for d_idx, folder_name in enumerate(dir_parts, start=1):
                    next_path = f"{cur_path}/{folder_name}" if cur_path else folder_name
                    if next_path not in dir_nodes:
                        dir_nodes[next_path] = {
                            "dir_path": next_path,
                            "name": folder_name,
                            "depth": d_idx,
                            "parent_path": cur_path,
                            "files": [],
                            "children_paths": set(),
                        }
                    dir_nodes[cur_path]["children_paths"].add(next_path)
                    cur_path = next_path
                file_to_dir[fp] = cur_path
                dir_nodes[cur_path]["files"].append(fp)

        # Compute file connectivity and inter-folder call ratios
        inbound: Dict[str, int] = {k: 0 for k in dir_nodes}
        outbound: Dict[str, int] = {k: 0 for k in dir_nodes}
        file_connectivity: Dict[str, int] = {fp: 0 for fp in packages_dict}
        file_outbound: Dict[str, int] = {fp: 0 for fp in packages_dict}
        file_inbound: Dict[str, int] = {fp: 0 for fp in packages_dict}

        for l in links:
            s_node = node_by_id.get(l.get("source"))
            t_node = node_by_id.get(l.get("target"))
            if not s_node or not t_node:
                continue
            sf = s_node.get("filepath")
            tf = t_node.get("filepath")
            if not sf or not tf or sf not in packages_dict or tf not in packages_dict:
                continue

            file_connectivity[sf] += 1
            file_connectivity[tf] += 1
            if sf != tf:
                file_outbound[sf] += 1
                file_inbound[tf] += 1

            s_dir = file_to_dir.get(sf, "")
            t_dir = file_to_dir.get(tf, "")
            if s_dir != t_dir:
                outbound[s_dir] = outbound.get(s_dir, 0) + 1
                inbound[t_dir] = inbound.get(t_dir, 0) + 1

        def file_call_ratio(fp: str) -> float:
            tot = file_outbound[fp] + file_inbound[fp]
            return (file_outbound[fp] - file_inbound[fp]) / tot if tot > 0 else 0.0

        # Score each directory node and sort its direct files (callers at top -> callees at bottom)
        for d_path, d_info in dir_nodes.items():
            out_c = outbound.get(d_path, 0)
            in_c = inbound.get(d_path, 0)
            tot = out_c + in_c
            ratio = (out_c - in_c) / tot if tot > 0 else 0.0
            d_info["ratio"] = ratio
            if ratio > 0.35:
                d_info["role_tag"] = "INGRESS"
            elif ratio > 0.05:
                d_info["role_tag"] = "ORCHESTRATION"
            elif ratio >= -0.25:
                d_info["role_tag"] = "DOMAIN"
            else:
                d_info["role_tag"] = "FOUNDATION"

            d_info["files"].sort(
                key=lambda fp: (-file_call_ratio(fp), -file_connectivity.get(fp, 0), fp)
            )

        # Shift column indices left by 1 if there are no root files in Column 0
        has_root_files = len(dir_nodes[""]["files"]) > 0
        col_shift = 0 if has_root_files else -1

        zones_list: List[Dict[str, Any]] = []
        color_counter = 0

        def build_subtree(d_path: str) -> Dict[str, Any]:
            nonlocal color_counter
            info = dir_nodes[d_path]
            is_root = d_path == ""
            col_idx = max(0, info["depth"] + col_shift)

            if is_root:
                color = "#64748b"
                zone_id = "zone_root"
                display_name = "ROOT FILES"
            else:
                color = ZONE_PALETTE[color_counter % len(ZONE_PALETTE)]
                color_counter += 1
                zone_id = f"zone_d{col_idx}_{d_path.replace('/', '_')}"
                display_name = f"{info['name'].upper()} [{info['role_tag']}]"

            # Sort child folders by descending topological ratio, then name
            sorted_children_paths = sorted(
                info["children_paths"],
                key=lambda cp: (-dir_nodes[cp]["ratio"], dir_nodes[cp]["name"]),
            )
            children_nodes = [build_subtree(cp) for cp in sorted_children_paths]

            node_dict = {
                "id": zone_id,
                "index": len(zones_list),
                "dir_path": d_path,
                "name": display_name,
                "short_name": info["name"],
                "color": color,
                "depth": info["depth"],
                "col_idx": col_idx,
                "is_root_unckoned": is_root,
                "ratio": info["ratio"],
                "role_tag": info["role_tag"],
                "files": info["files"],
                "parent_path": info["parent_path"],
                "children": children_nodes,
            }
            if info["files"] or not is_root:
                zones_list.append(node_dict)
            return node_dict

        root_tree = build_subtree("")
        return {
            "root": root_tree,
            "zones": zones_list,
            "has_root_files": has_root_files,
        }

    @classmethod
    def classify_and_order_zones(
        cls,
        packages_dict: Dict[str, Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        links: List[Dict[str, Any]],
        scope: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Backwards-compatible flat zone list accessor."""
        funnel = cls.build_directory_funnel(packages_dict, nodes, links, scope=scope)
        return funnel["zones"]
