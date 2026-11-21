"""
Left-to-Right Hierarchical Directory Funnel Layout Engine.
Places root files in Column 0 without a zone enclosure, expands subfolders into
columns from left (narrow) to right (wide), wraps large zones (> zone_grid_threshold)
into multi-column grids, and aligns parent folders with their child subtrees.
"""

import math
import os
from typing import Dict, List, Any, Optional, Tuple
from ..config import CircuitConfig
from .zone_classifier import build_directory_funnel
from .package_sizer import PackageSizer
from ..routing.channel_router import OrthogonalChannelRouter


class CircuitLayoutEngine:
    """
    Arranges code packages and symbols into a Left-to-Right Directory Funnel.
    """

    def __init__(
        self,
        config: Optional[CircuitConfig] = None,
        grid_size: Optional[int] = None,
        chip_margin_x: Optional[int] = None,
        chip_margin_y: Optional[int] = None,
        zone_margin_x: Optional[int] = None,
        zone_margin_y: Optional[int] = None,
    ):
        self.config = config or CircuitConfig.load()
        if grid_size is not None:
            self.config.grid_size = grid_size
        if chip_margin_x is not None:
            self.config.layout.chip_margin_x = chip_margin_x
        if chip_margin_y is not None:
            self.config.layout.chip_margin_y = chip_margin_y
        if zone_margin_x is not None:
            self.config.layout.column_highway_w = zone_margin_x
        if zone_margin_y is not None:
            self.config.layout.zone_margin_y = zone_margin_y

        self.grid_size = self.config.grid_size
        self.sizer = PackageSizer(grid_size=self.grid_size, sizer_cfg=self.config.sizer)
        self.router = OrthogonalChannelRouter(config=self.config)

    def _snap(self, val: float) -> int:
        return int(round(val / self.grid_size) * self.grid_size)

    def _measure_zone_grid(
        self,
        z_node: Dict[str, Any],
        bps: List[Dict[str, Any]],
        pkg_traffic: Optional[Dict[str, Tuple[int, int]]] = None,
    ):
        """
        Computes internal multi-column grid dimensions for a single folder zone.
        Root files (is_root_unckoned) stack in a single column without zone padding.
        Folder zones with > zone_grid_threshold files wrap into zone_max_cols columns.
        Gaps between sub-columns and rows are dynamically sized based on passing connections.
        """
        lcfg = self.config.layout
        rcfg = self.config.routing
        track_step = rcfg.track_step
        pkg_traffic = pkg_traffic or {}
        num_files = len(bps)
        is_root = z_node.get("is_root_unckoned", False)

        if num_files == 0:
            # Folder has no direct files, only subfolders: minimal relay header badge
            z_node["grid_cols"] = 1
            z_node["own_w"] = 280 if not is_root else 0
            z_node["own_h"] = 64 if not is_root else 0
            z_node["col_widths"] = [280] if not is_root else [0]
            z_node["row_heights"] = [64] if not is_root else [0]
            z_node["col_gaps"] = []
            z_node["row_gaps"] = []
            return

        max_c = max(1, getattr(lcfg, "zone_max_cols", 5))
        threshold = getattr(lcfg, "zone_grid_threshold", 2)
        target_ratio = getattr(lcfg, "zone_target_aspect_ratio", 2.0)

        if num_files == 1:
            best_cols = 1
        elif is_root:
            best_cols = min(num_files, max_c)
        else:
            best_cols = 1
            best_score = float("inf")
            candidates = list(range(1, min(num_files, max_c) + 1))
            if num_files >= threshold and len(candidates) > 1:
                candidates = [c for c in candidates if c > 1]

            for c in candidates:
                num_rows = math.ceil(num_files / c)
                c_widths = [0] * c
                r_heights = []
                for r in range(num_rows):
                    row_bps = bps[r * c : (r + 1) * c]
                    rh = 0
                    for c_idx, bp in enumerate(row_bps):
                        c_widths[c_idx] = max(c_widths[c_idx], bp["width"])
                        rh = max(rh, bp["height"])
                    r_heights.append(rh)
                cand_w = sum(c_widths) + max(0, c - 1) * lcfg.chip_margin_x
                cand_h = sum(r_heights) + max(0, num_rows - 1) * lcfg.chip_margin_y
                ratio = cand_w / cand_h if cand_h > 0 else 1.0

                # Strongly penalize tall zones (ratio < 1.0) and moderately penalize ratio < 1.3
                if ratio < 1.0:
                    score = 100.0 + (1.0 - ratio) * 50.0
                elif ratio < 1.3:
                    score = 25.0 + (1.3 - ratio) * 20.0
                else:
                    score = abs(ratio - target_ratio)

                if score < best_score:
                    best_score = score
                    best_cols = c

        cols = best_cols

        # Partition files into rows of `cols` columns
        col_widths = [0] * cols
        row_heights = []
        num_rows = math.ceil(num_files / cols)

        for r in range(num_rows):
            row_bps = bps[r * cols : (r + 1) * cols]
            row_h = 0
            for c_idx, bp in enumerate(row_bps):
                col_widths[c_idx] = max(col_widths[c_idx], bp["width"])
                row_h = max(row_h, bp["height"])
            row_heights.append(row_h)

        # Dynamically size gaps between sub-columns based on passing connection traffic
        col_gaps = []
        for ci in range(cols - 1):
            out_c = max(
                [pkg_traffic.get(bps[r * cols + ci]["filepath"], (0, 0))[0]
                 for r in range(num_rows) if r * cols + ci < len(bps)] or [0]
            )
            in_next = max(
                [pkg_traffic.get(bps[r * cols + ci + 1]["filepath"], (0, 0))[1]
                 for r in range(num_rows) if r * cols + ci + 1 < len(bps)] or [0]
            )
            gap = max(lcfg.chip_margin_x, (out_c + in_next + 6) * track_step)
            col_gaps.append(gap)

        # Dynamically size gaps between rows based on passing connections
        row_gaps = []
        for ri in range(num_rows - 1):
            row_fps = {bps[ri * cols + ci]["filepath"] for ci in range(cols) if ri * cols + ci < len(bps)}
            row_conns = sum(pkg_traffic.get(fp, (0, 0))[0] + pkg_traffic.get(fp, (0, 0))[1] for fp in row_fps)
            gap = max(lcfg.chip_margin_y, (row_conns + 4) * track_step)
            row_gaps.append(gap)

        # Dynamically size zone bottom padding based on last row traffic
        last_row_fps = {bps[(num_rows - 1) * cols + ci]["filepath"] for ci in range(cols) if (num_rows - 1) * cols + ci < len(bps)}
        last_row_conns = sum(pkg_traffic.get(fp, (0, 0))[0] + pkg_traffic.get(fp, (0, 0))[1] for fp in last_row_fps)
        zone_pad_bottom = max(lcfg.zone_padding_bottom, (last_row_conns + 6) * track_step)

        inner_w = sum(col_widths) + sum(col_gaps)
        inner_h = sum(row_heights) + sum(row_gaps)

        # Dynamically size zone left and right margins based on edge column traffic
        first_col_in = max(
            [pkg_traffic.get(bps[r * cols]["filepath"], (0, 0))[1]
             for r in range(num_rows) if r * cols < len(bps)] or [0]
        )
        last_col_out = max(
            [pkg_traffic.get(bps[r * cols + cols - 1]["filepath"], (0, 0))[0]
             for r in range(num_rows) if r * cols + cols - 1 < len(bps)] or [0]
        )
        zone_pad_left = max(lcfg.zone_padding_x, (first_col_in + 4) * track_step)
        zone_pad_right = max(lcfg.zone_padding_x, (last_col_out + 4) * track_step)

        if is_root:
            own_w = inner_w
            own_h = inner_h
        else:
            own_w = max(360, inner_w + zone_pad_left + zone_pad_right)
            own_h = inner_h + lcfg.zone_padding_top + zone_pad_bottom

        z_node["grid_cols"] = cols
        z_node["col_widths"] = col_widths
        z_node["row_heights"] = row_heights
        z_node["col_gaps"] = col_gaps
        z_node["row_gaps"] = row_gaps
        z_node["zone_pad_left"] = zone_pad_left
        z_node["zone_pad_right"] = zone_pad_right
        z_node["zone_pad_bottom"] = zone_pad_bottom
        z_node["own_w"] = self._snap(own_w)
        z_node["own_h"] = self._snap(own_h)

    def apply_circuit_layout(self, graph_dict: Dict[str, Any]) -> Dict[str, Any]:
        nodes = graph_dict.get("nodes", [])
        links = graph_dict.get("links", [])
        raw_packages = graph_dict.get("packages", [])

        if not nodes and not raw_packages:
            return graph_dict

        lcfg = self.config.layout
        node_by_id = {n["id"]: n for n in nodes}

        packages_dict: Dict[str, Dict[str, Any]] = {}
        for p in raw_packages:
            fp = p.get("filepath") or p.get("id")
            if fp:
                packages_dict[fp] = dict(p)

        nodes_by_file: Dict[str, List[Dict[str, Any]]] = {}
        for n in nodes:
            fp = n.get("filepath")
            if fp:
                nodes_by_file.setdefault(fp, []).append(n)
                if fp not in packages_dict:
                    packages_dict[fp] = {
                        "id": fp,
                        "filepath": fp,
                        "filename": os.path.basename(fp),
                    }

        # Precompute per-node in/out connection counts to allocate dynamic vertical staircase headroom
        node_edge_counts: Dict[str, Tuple[int, int]] = {}
        # Precompute per-package cross-package traffic (outgoing, incoming) for dynamic highway sizing
        pkg_traffic: Dict[str, Tuple[int, int]] = {}
        for l in links:
            src = l.get("source")
            tgt = l.get("target")
            if src:
                in_c, out_c = node_edge_counts.get(src, (0, 0))
                node_edge_counts[src] = (in_c, out_c + 1)
            if tgt and not l.get("is_hub_stub"):
                in_c, out_c = node_edge_counts.get(tgt, (0, 0))
                node_edge_counts[tgt] = (in_c + 1, out_c)
            sn, tn = node_by_id.get(src), node_by_id.get(tgt)
            if sn and tn:
                sf, tf = sn.get("filepath"), tn.get("filepath")
                if sf and tf and sf != tf:
                    out_c, in_c = pkg_traffic.get(sf, (0, 0))
                    pkg_traffic[sf] = (out_c + 1, in_c)
                    if not l.get("is_hub_stub"):
                        out_t, in_t = pkg_traffic.get(tf, (0, 0))
                        pkg_traffic[tf] = (out_t, in_t + 1)

        # 1. Build Recursive Directory Funnel Tree
        funnel = build_directory_funnel(
            packages_dict,
            nodes,
            links,
            scope=graph_dict.get("scope"),
            project_root=graph_dict.get("project_root"),
        )
        root_tree = funnel["root"]

        # 2. Pass 1 (Bottom-Up): Measure Package Blueprints, Zone Grids, Column Widths & Subtree Heights
        col_max_width: Dict[int, int] = {}
        blueprints_by_zone: Dict[str, List[Dict[str, Any]]] = {}

        def measure_subtree(z_node: Dict[str, Any]) -> int:
            bps = []
            for fp in z_node["files"]:
                bp = self.sizer.compute_package_blueprint(
                    filepath=fp,
                    pkg_meta=packages_dict[fp],
                    syms=nodes_by_file.get(fp, []),
                    zone_idx=z_node["index"],
                    zone_color=z_node["color"],
                    node_edge_counts=node_edge_counts,
                )
                bps.append(bp)
            blueprints_by_zone[z_node["id"]] = bps
            self._measure_zone_grid(z_node, bps, pkg_traffic)

            c_idx = z_node["col_idx"]
            if z_node["own_w"] > 0:
                col_max_width[c_idx] = max(col_max_width.get(c_idx, 320), z_node["own_w"])

            children = z_node.get("children", [])
            children_total_h = 0
            for idx, child in enumerate(children):
                ch_h = measure_subtree(child)
                children_total_h += ch_h
                if idx > 0:
                    children_total_h += lcfg.zone_margin_y

            z_node["children_total_h"] = children_total_h
            z_node["subtree_h"] = max(z_node["own_h"], children_total_h)
            return z_node["subtree_h"]

        total_funnel_h = measure_subtree(root_tree)

        # Dynamically size inter-column highway gaps based on passing traffic
        file_col: Dict[str, int] = {}
        file_zone: Dict[str, str] = {}
        def collect_file_placements(z_node: Dict[str, Any]):
            c = z_node["col_idx"]
            zid = z_node["id"]
            for fp in z_node.get("files", []):
                file_col[fp] = c
                file_zone[fp] = zid
            for child in z_node.get("children", []):
                collect_file_placements(child)

        collect_file_placements(root_tree)

        col_l4_count: Dict[int, int] = {}
        col_l5_depart_right: Dict[int, int] = {}
        col_l5_transit_right: Dict[int, int] = {}
        col_l5_arrive_left: Dict[int, int] = {}
        col_l5_transit_left: Dict[int, int] = {}

        for l in links:
            s_id = l.get("source")
            t_id = l.get("target")
            sn = node_by_id.get(s_id)
            tn = node_by_id.get(t_id)
            if not sn or not tn:
                continue
            sf = sn.get("filepath")
            tf = tn.get("filepath")
            if not sf or not tf or sf == tf:
                continue
            sc = file_col.get(sf)
            tc = file_col.get(tf)
            sz = file_zone.get(sf)
            tz = file_zone.get(tf)
            if sc is None or tc is None:
                continue
            if sc == tc and sz != tz:
                col_l4_count[sc] = col_l4_count.get(sc, 0) + 1
            elif sc != tc:
                if tc > sc:
                    col_l5_depart_right[sc] = col_l5_depart_right.get(sc, 0) + 1
                    col_l5_arrive_left[tc] = col_l5_arrive_left.get(tc, 0) + 1
                    for mid_c in range(sc + 1, tc):
                        col_l5_transit_right[mid_c] = col_l5_transit_right.get(mid_c, 0) + 1
                else:
                    col_l5_transit_left[sc] = col_l5_transit_left.get(sc, 0) + 1

        rcfg = self.config.routing
        track_step = rcfg.track_step

        col_intra_w: Dict[int, int] = {}
        col_depart_w: Dict[int, int] = {}
        col_arrive_w: Dict[int, int] = {}
        col_gap_w: Dict[int, int] = {}
        sorted_cols = sorted(col_max_width.keys())

        for c_idx in sorted_cols:
            n_intra = col_l4_count.get(c_idx, 0)
            n_depart = col_l5_depart_right.get(c_idx, 0) + col_l5_transit_right.get(c_idx, 0)
            n_arrive = col_l5_arrive_left.get(c_idx + 1, 0) + col_l5_transit_left.get(c_idx, 0)

            intra_w = self._snap(max(140, (n_intra + 6) * track_step))
            depart_w = self._snap(max(120, (n_depart + 4) * track_step))
            arrive_w = self._snap(max(120, (n_arrive + 4) * track_step))
            corridor_buffer = 40

            col_intra_w[c_idx] = intra_w
            col_depart_w[c_idx] = depart_w
            col_arrive_w[c_idx] = arrive_w

            if c_idx == sorted_cols[-1]:
                col_gap_w[c_idx] = 0
            else:
                col_gap_w[c_idx] = intra_w + corridor_buffer + depart_w + corridor_buffer + arrive_w

        # Compute deterministic X origins for each depth column (Left -> Right)
        col_x_origin: Dict[int, int] = {}
        cur_col_x = lcfg.board_margin_x
        for c_idx in sorted_cols:
            col_x_origin[c_idx] = self._snap(cur_col_x)
            cur_col_x += col_max_width[c_idx] + col_gap_w[c_idx]

        max_board_width = cur_col_x + lcfg.board_margin_x

        # 3. Pass 2 (Top-Down): Place Zones & Packages inside Allocated Vertical Subtree Intervals
        placed_packages: Dict[str, Dict[str, Any]] = {}
        zone_banners: List[Dict[str, Any]] = []
        zone_hierarchy: Dict[str, Dict[str, Any]] = {}

        def place_subtree(
            z_node: Dict[str, Any],
            y_top: int,
            parent_banner: Optional[Dict[str, Any]] = None,
        ):
            c_idx = z_node["col_idx"]
            is_root = z_node.get("is_root_unckoned", False)
            own_w = z_node["own_w"]
            own_h = z_node["own_h"]
            subtree_h = z_node["subtree_h"]

            zone_x = col_x_origin.get(c_idx, lcfg.board_margin_x)
            if lcfg.align_zone_in_subtree == "center" and subtree_h > own_h:
                zone_y = self._snap(y_top + (subtree_h - own_h) / 2.0)
            else:
                zone_y = self._snap(y_top)

            bps = blueprints_by_zone.get(z_node["id"], [])
            cols = z_node.get("grid_cols", 1)
            col_widths = z_node.get("col_widths", [own_w])
            row_heights = z_node.get("row_heights", [])

            zone_pad_left = z_node.get("zone_pad_left", lcfg.zone_padding_x)
            start_x = zone_x if is_root else zone_x + zone_pad_left
            start_y = zone_y if is_root else zone_y + lcfg.zone_padding_top

            col_gaps = z_node.get("col_gaps", [lcfg.chip_margin_x] * max(0, cols - 1))
            row_gaps = z_node.get("row_gaps", [lcfg.chip_margin_y] * max(0, len(row_heights) - 1))

            zone_pad_bottom = z_node.get("zone_pad_bottom", lcfg.zone_padding_bottom)

            # Compute horizontal highway and channel boundaries for each grid row
            row_bottom_highways = []
            row_channel_bounds = []  # list of (min_y, max_y)
            cur_r_bottom = start_y
            num_rows = len(row_heights)
            for r_idx, rh in enumerate(row_heights):
                row_bot = cur_r_bottom + rh
                if r_idx < num_rows - 1:
                    gap = row_gaps[r_idx] if r_idx < len(row_gaps) else lcfg.chip_margin_y
                    hw_y = self._snap(row_bot + gap * 0.5)
                    row_bottom_highways.append(hw_y)
                    row_channel_bounds.append((row_bot + 6, row_bot + gap - 6))
                    cur_r_bottom = row_bot + gap
                else:
                    # Last row: sits inside zone bottom padding
                    hw_y = self._snap(row_bot + max(28, int(zone_pad_bottom * 0.5)))
                    row_bottom_highways.append(hw_y)
                    row_channel_bounds.append((row_bot + 6, row_bot + zone_pad_bottom - 14))

            # Zone left incoming highway and right outgoing highway
            zone_road_in_x = self._snap(zone_x + 16)
            zone_road_out_x = self._snap(zone_x + own_w - 16)

            # Instantiate files inside the zone's grid
            for idx, bp in enumerate(bps):
                r = idx // cols
                c = idx % cols
                cell_offset_x = sum(col_widths[:c]) + sum(col_gaps[:c])
                cell_offset_y = sum(row_heights[:r]) + sum(row_gaps[:r])

                pkg_x = self._snap(start_x + cell_offset_x)
                pkg_y = self._snap(start_y + cell_offset_y)

                pkg_info = self.sizer.instantiate_package(
                    bp,
                    pkg_x=pkg_x,
                    pkg_y=pkg_y,
                    zone_id=z_node["id"],
                    col_idx=c_idx,
                    sub_col_idx=c,
                )
                pkg_info["grid_row"] = r
                pkg_info["grid_col"] = c
                pkg_info["row_bottom_highway_y"] = row_bottom_highways[r] if r < len(row_bottom_highways) else pkg_y + pkg_info["height"] + 24
                pkg_info["row_highway_min_y"] = row_channel_bounds[r][0] if r < len(row_channel_bounds) else pkg_info["row_bottom_highway_y"] - 20
                pkg_info["row_highway_max_y"] = row_channel_bounds[r][1] if r < len(row_channel_bounds) else pkg_info["row_bottom_highway_y"] + 24
                pkg_info["v_road_left"] = self._snap(pkg_x - 14)
                pkg_info["v_road_right"] = self._snap(pkg_x + pkg_info["width"] + 14)
                pkg_info["zone_road_in_x"] = zone_road_in_x
                pkg_info["zone_road_out_x"] = zone_road_out_x
                placed_packages[bp["filepath"]] = pkg_info

            current_banner = None
            if not is_root or bps:
                current_banner = {
                    "id": z_node["id"],
                    "name": z_node["name"],
                    "color": z_node["color"],
                    "x": zone_x,
                    "y": zone_y,
                    "width": max(280, own_w),
                    "height": max(64, own_h),
                    "file_count": len(bps),
                    "col_idx": c_idx,
                    "is_root": 1 if is_root else 0,
                    "parent_x": parent_banner["x"] + parent_banner["width"] if parent_banner else -1,
                    "parent_y": parent_banner["y"] + parent_banner["height"] // 2 if parent_banner else -1,
                }
                # Only emit visible zone enclosure banners for actual folders (root files have no zone)
                if not is_root:
                    zone_banners.append(current_banner)

                # Compute sub-column vertical bus X tracks inside this zone for Level-3 Intra-Zone routing
                sub_col_buses = []
                cur_sx = start_x
                for c_idx_w, cw in enumerate(col_widths):
                    gap = col_gaps[c_idx_w] if c_idx_w < len(col_gaps) else 0
                    bus_off = max(20, gap // 2)
                    sub_col_buses.append(int(cur_sx + cw + bus_off))
                    cur_sx += cw + gap

                zone_hierarchy[z_node["id"]] = {
                    "id": z_node["id"],
                    "col_idx": c_idx,
                    "x": zone_x,
                    "y": zone_y,
                    "width": max(280, own_w),
                    "height": max(64, own_h),
                    "road_in_x": zone_road_in_x,
                    "road_out_x": zone_road_out_x,
                    "row_bottom_highways": row_bottom_highways,
                    "y_interval_top": y_top,
                    "y_interval_bottom": y_top + subtree_h,
                    "spine_above_y": self._snap(y_top - lcfg.zone_margin_y * 0.45),
                    "spine_below_y": self._snap(y_top + subtree_h + lcfg.zone_margin_y * 0.45),
                    "sub_col_buses": sub_col_buses,
                    "right_bus_x": int(zone_x + max(280, own_w) - 18),
                    "left_bus_x": int(zone_x + 18),
                }

            # Place child folders in Column c_idx + 1 within [y_top, y_top + subtree_h]
            children = z_node.get("children", [])
            if children:
                children_h = z_node["children_total_h"]
                child_y = self._snap(y_top + max(0, (subtree_h - children_h) / 2.0))
                for child in children:
                    place_subtree(
                        child,
                        y_top=child_y,
                        parent_banner=current_banner if not is_root else None,
                    )
                    child_y += child["subtree_h"] + lcfg.zone_margin_y

        place_subtree(root_tree, y_top=lcfg.board_margin_y, parent_banner=None)

        # Build dynamically sized column highway metadata for Level-4 & Level-5 routing
        column_highways: Dict[int, Dict[str, int]] = {}

        for c_idx in sorted_cols:
            cx = col_x_origin[c_idx]
            cw = col_max_width[c_idx]
            r_edge = cx + cw
            gap_w = col_gap_w.get(c_idx, 0)
            intra_w = col_intra_w.get(c_idx, 140)
            depart_w = col_depart_w.get(c_idx, 120)
            arrive_w = col_arrive_w.get(c_idx, 120)
            corridor_buffer = 40

            # 1. Local intra-column highway (Level 4: zone to zone inside same column)
            intra_min_x = r_edge + 16
            intra_max_x = intra_min_x + intra_w
            intra_hw_x = (intra_min_x + intra_max_x) // 2

            # 2. Inter-column departure highway (Level 5: cross-column going right)
            cross_min_x = intra_max_x + corridor_buffer
            cross_max_x = cross_min_x + depart_w
            cross_exit_x = (cross_min_x + cross_max_x) // 2

            # 3. Inter-column arrival highway from left (Level 5: entering next column from left)
            next_cx = col_x_origin.get(c_idx + 1, r_edge + gap_w)
            cross_entry_max_x = next_cx - 16
            cross_entry_min_x = cross_entry_max_x - arrive_w
            cross_entry_x = (cross_entry_min_x + cross_entry_max_x) // 2

            left_entry_x = cx - 16 - arrive_w // 2
            left_entry_min_x = cx - 16 - arrive_w
            left_entry_max_x = cx - 16
            left_exit_x = cx - (depart_w // 2 + 16)
            left_exit_min_x = cx - depart_w - 16
            left_exit_max_x = cx - 16

            column_highways[c_idx] = {
                "col_idx": c_idx,
                "x": cx,
                "width": cw,
                "intra_col_highway_x": int(intra_hw_x),
                "intra_col_min_x": int(intra_min_x),
                "intra_col_max_x": int(intra_max_x),
                "right_exit_x": int(cross_exit_x),
                "right_exit_min_x": int(cross_min_x),
                "right_exit_max_x": int(cross_max_x),
                "right_entry_x": int(cross_exit_x),
                "right_entry_min_x": int(cross_min_x),
                "right_entry_max_x": int(cross_max_x),
                "left_entry_x": int(left_entry_x),
                "left_entry_min_x": int(left_entry_min_x),
                "left_entry_max_x": int(left_entry_max_x),
                "left_exit_x": int(left_exit_x),
                "left_exit_min_x": int(left_exit_min_x),
                "left_exit_max_x": int(left_exit_max_x),
                "cross_col_exit_x": int(cross_exit_x),
                "cross_col_min_x": int(cross_min_x),
                "cross_col_max_x": int(cross_max_x),
                "cross_col_entry_x": int(cross_entry_x),
                "cross_col_entry_min_x": int(cross_entry_min_x),
                "cross_col_entry_max_x": int(cross_entry_max_x),
                "cross_col_left_exit_x": int(left_exit_x),
                "cross_col_left_min_x": int(left_exit_min_x),
                "cross_col_left_max_x": int(left_exit_max_x),
                "cross_col_right_entry_x": int(r_edge + gap_w - 32),
                "left_highway_x": int(cross_entry_x),
                "right_highway_x": int(cross_exit_x),
            }

        # Compute Horizontal Trunk Highways (Crossbar Bridges)
        board_h = total_funnel_h + lcfg.board_margin_y * 2
        center_y = self._snap(board_h / 2.0)
        if rcfg.trunk_highway_positions:
            trunk_highways = [self._snap(y) for y in rcfg.trunk_highway_positions]
        elif rcfg.trunk_highway_mode == "center" or rcfg.trunk_highway_count <= 1:
            trunk_highways = [center_y]
        else:
            spacing = rcfg.trunk_highway_spacing
            count = rcfg.trunk_highway_count
            half = count // 2
            raw_trunks = [center_y + i * spacing for i in range(-half, half + 1)]
            trunk_highways = [
                self._snap(y)
                for y in raw_trunks
                if lcfg.board_margin_y + 100 <= y <= board_h - lcfg.board_margin_y - 100
            ]
            if not trunk_highways:
                trunk_highways = [center_y]
        trunk_highways = sorted(list(set(trunk_highways)))

        # 4. Assign Directional Perimeter Pins
        self._assign_perimeter_pins(nodes, links, node_by_id)

        # 5. LCA-Guided Hierarchical Escape Routing
        self.router.route_all_edges(
            nodes=nodes,
            links=links,
            placed_packages=placed_packages,
            node_by_id=node_by_id,
            zone_hierarchy=zone_hierarchy,
            column_highways=column_highways,
            trunk_highways=trunk_highways,
        )

        graph_dict["packages"] = list(placed_packages.values())
        graph_dict["zone_banners"] = zone_banners
        graph_dict["trunk_highways"] = trunk_highways
        graph_dict["board_width"] = int(max_board_width)
        graph_dict["board_height"] = int(total_funnel_h + lcfg.board_margin_y * 2)
        return graph_dict

    def _assign_perimeter_pins(
        self,
        nodes: List[Dict[str, Any]],
        links: List[Dict[str, Any]],
        node_by_id: Dict[str, Dict[str, Any]],
    ):
        node_out_edges: Dict[str, List[Dict[str, Any]]] = {}
        node_in_edges: Dict[str, List[Dict[str, Any]]] = {}
        for l in links:
            node_out_edges.setdefault(l["source"], []).append(l)
            if not l.get("is_hub_stub"):
                node_in_edges.setdefault(l["target"], []).append(l)

        for n in nodes:
            nw = n.get("width", 140)
            nh = n.get("height", 20)
            max_span = max(16, nw - 24)

            out_edges = node_out_edges.get(n["id"], [])
            out_count = len(out_edges)
            step_out = min(10, max_span / max(1, out_count))
            for rank, e in enumerate(out_edges):
                offset_x = (rank - (out_count - 1) / 2.0) * step_out if out_count > 1 else 0.0
                e["src_pin"] = (self._snap(n["x"] + offset_x), self._snap(n["y"] + nh / 2))
                e["src_rank"] = rank
                e["out_count"] = out_count

            in_edges = node_in_edges.get(n["id"], [])
            in_count = len(in_edges)
            step_in = min(10, max_span / max(1, in_count))
            for rank, e in enumerate(in_edges):
                offset_x = (rank - (in_count - 1) / 2.0) * step_in if in_count > 1 else 0.0
                e["tgt_pin"] = (self._snap(n["x"] + offset_x), self._snap(n["y"] - nh / 2))
                e["tgt_rank"] = rank
                e["in_count"] = in_count

            n["in_pin"] = (int(n["x"]), self._snap(n["y"] - nh / 2))
            n["out_pin"] = (int(n["x"]), self._snap(n["y"] + nh / 2))

