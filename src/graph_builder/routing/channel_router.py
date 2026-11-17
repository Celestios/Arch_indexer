"""
5-Level Lowest Common Ancestor (LCA) Hierarchical Escape Router.
Clears hierarchy boundaries sequentially:
Level 1: Node -> Class internal vertical side-rail
Level 2: Class -> File Package internal vertical side-rail
Level 3: File -> Zone internal sub-column vertical bus
Level 4: Zone -> Column vertical highway
Level 5: Column -> Cross-column horizontal inter-zone spine -> Target Column vertical highway
"""

from typing import Dict, List, Any, Tuple, Optional
from ..config import CircuitConfig, RoutingConfig


class OrthogonalChannelRouter:
    """
    Computes deterministic, least-turn orthogonal polylines guided by the funnel hierarchy.
    """

    def __init__(
        self,
        config: Optional[CircuitConfig] = None,
        grid_size: int = 8,
        chip_margin_x: int = 144,
        chip_margin_y: int = 112,
    ):
        self.config = config or CircuitConfig.load()
        self.rcfg: RoutingConfig = self.config.routing
        self.grid_size = self.config.grid_size
        self.chip_margin_x = self.config.layout.chip_margin_x if config else chip_margin_x
        self.chip_margin_y = self.config.layout.chip_margin_y if config else chip_margin_y

    @staticmethod
    def _segment_hits_box(
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        box: Tuple[float, float, float, float],
    ) -> bool:
        bx1, by1, bx2, by2 = box
        sx1, sx2 = min(x1, x2), max(x1, x2)
        sy1, sy2 = min(y1, y2), max(y1, y2)
        return not (sx2 < bx1 or sx1 > bx2 or sy2 < by1 or sy1 > by2)

    @staticmethod
    def _simplify_collinear(pts: List[int]) -> List[int]:
        """Removes redundant collinear intermediate waypoints to guarantee least turns."""
        if len(pts) < 6:
            return pts
        out = [pts[0], pts[1]]
        for i in range(2, len(pts), 2):
            x, y = pts[i], pts[i + 1]
            if len(out) >= 4:
                x1, y1 = out[-4], out[-3]
                x2, y2 = out[-2], out[-1]
                if (x1 == x2 == x) or (y1 == y2 == y):
                    out[-2], out[-1] = x, y
                    continue
            if len(out) >= 2 and out[-2] == x and out[-1] == y:
                continue
            out.extend([x, y])
        return out

    def route_all_edges(
        self,
        nodes: List[Dict[str, Any]],
        links: List[Dict[str, Any]],
        placed_packages: Dict[str, Dict[str, Any]],
        node_by_id: Dict[str, Dict[str, Any]],
        zone_hierarchy: Optional[Dict[str, Dict[str, Any]]] = None,
        column_highways: Optional[Dict[int, Dict[str, int]]] = None,
        trunk_highways: Optional[List[int]] = None,
    ):
        zone_hierarchy = zone_hierarchy or {}
        column_highways = column_highways or {}
        if not trunk_highways:
            max_y = max((p["y"] + p["height"] for p in placed_packages.values()), default=10000)
            trunk_highways = [int(round((max_y / 2.0) / 8.0) * 8.0)]
        rcfg = self.rcfg

        claimed_h_tracks: Dict[int, List[Tuple[float, float]]] = {}
        claimed_v_tracks: Dict[int, List[Tuple[float, float]]] = {}

        pkg_obstacles: Dict[str, Tuple[float, float, float, float]] = {}
        for fp, p in placed_packages.items():
            pkg_obstacles[fp] = (
                p["x"] - 8,
                p["y"] - 22,
                p["x"] + p["width"] + 8,
                p["y"] + p["height"] + 8,
            )

        def claim_interval(
            table: Dict[int, List[Tuple[float, float]]],
            track: int,
            start: float,
            end: float,
        ):
            pad = rcfg.lane_clearance
            low = min(start, end) - pad
            high = max(start, end) + pad
            table.setdefault(track, []).append((low, high))

        def find_clear_h_track(
            base_y: float,
            x1: float,
            x2: float,
            ignore_fps: Tuple[str, ...],
            step: int = rcfg.track_step,
            min_y: Optional[float] = None,
            max_y: Optional[float] = None,
        ) -> int:
            low, high = min(x1, x2), max(x1, x2)
            snap = float(rcfg.track_snap)
            offsets = [0]
            for k in range(1, 60):
                offsets.extend([k * step, -k * step])
            for off in offsets:
                ty = int(round((base_y + off) / snap) * snap)
                if min_y is not None and ty < min_y:
                    continue
                if max_y is not None and ty > max_y:
                    continue
                intervals = claimed_h_tracks.get(ty, [])
                if any(not (high < inv[0] or low > inv[1]) for inv in intervals):
                    continue
                blocked = False
                for fp, box in pkg_obstacles.items():
                    if fp in ignore_fps:
                        continue
                    if self._segment_hits_box(low, ty, high, ty, box):
                        blocked = True
                        break
                if not blocked:
                    claim_interval(claimed_h_tracks, ty, low, high)
                    return ty
            fallback_y = int(round(base_y / snap) * snap)
            if min_y is not None:
                fallback_y = max(int(min_y), fallback_y)
            if max_y is not None:
                fallback_y = min(int(max_y), fallback_y)
            claim_interval(claimed_h_tracks, fallback_y, low, high)
            return fallback_y

        def find_clear_v_track(
            base_x: float,
            y1: float,
            y2: float,
            ignore_fps: Tuple[str, ...],
            step: int = rcfg.track_step,
            min_x: Optional[float] = None,
            max_x: Optional[float] = None,
        ) -> int:
            low, high = min(y1, y2), max(y1, y2)
            snap = float(rcfg.track_snap)
            offsets = [0]
            for k in range(1, 80):
                offsets.extend([k * step, -k * step])
            for off in offsets:
                tx = int(round((base_x + off) / snap) * snap)
                if min_x is not None and tx < min_x:
                    continue
                if max_x is not None and tx > max_x:
                    continue
                intervals = claimed_v_tracks.get(tx, [])
                if any(not (high < inv[0] or low > inv[1]) for inv in intervals):
                    continue
                blocked = False
                for fp, box in pkg_obstacles.items():
                    if fp in ignore_fps:
                        continue
                    if self._segment_hits_box(tx, low, tx, high, box):
                        blocked = True
                        break
                if not blocked:
                    claim_interval(claimed_v_tracks, tx, low, high)
                    return tx
            fallback_x = int(round(base_x / snap) * snap)
            if min_x is not None:
                fallback_x = max(int(min_x), fallback_x)
            if max_x is not None:
                fallback_x = min(int(max_x), fallback_x)
            claim_interval(claimed_v_tracks, fallback_x, low, high)
            return fallback_x

        class_rail_counts: Dict[str, int] = {}
        file_rail_counts: Dict[str, int] = {}

        # Precompute cross-package traffic for dynamic escape/arrival corridor sizing
        pkg_traffic: Dict[str, Tuple[int, int]] = {}
        for l in links:
            s_id, t_id = l.get("source"), l.get("target")
            sn, tn = node_by_id.get(s_id), node_by_id.get(t_id)
            if sn and tn:
                sf, tf = sn.get("filepath"), tn.get("filepath")
                if sf and tf and sf != tf:
                    out_c, in_c = pkg_traffic.get(sf, (0, 0))
                    pkg_traffic[sf] = (out_c + 1, in_c)
                    if not l.get("is_hub_stub"):
                        out_t, in_t = pkg_traffic.get(tf, (0, 0))
                        pkg_traffic[tf] = (out_t, in_t + 1)

        for l in links:
            sp = l.get("src_pin")
            if not sp:
                continue

            # 0. High-Fan-In Hub Stub
            if l.get("is_hub_stub"):
                l["waypoints"] = [
                    int(sp[0]),
                    int(sp[1]),
                    int(sp[0]),
                    int(sp[1] + rcfg.hub_stub_length),
                ]
                continue

            sn = node_by_id.get(l["source"])
            tn = node_by_id.get(l["target"])
            if not sn or not tn:
                continue

            tp = l.get("tgt_pin") or tn.get("in_pin") or (tn["x"], tn["y"] - tn["height"] / 2)
            sf = sn.get("filepath")
            tf = tn.get("filepath")

            if sf not in placed_packages or tf not in placed_packages:
                mid_y = int((sp[1] + tp[1]) / 2)
                l["waypoints"] = [int(sp[0]), int(sp[1]), int(sp[0]), mid_y, int(tp[0]), mid_y, int(tp[0]), int(tp[1])]
                continue

            spkg = placed_packages[sf]
            tpkg = placed_packages[tf]

            s_cls = sn.get("class_box_id")
            t_cls = tn.get("class_box_id")

            src_rank = l.get("src_rank", 0)
            tgt_rank = l.get("tgt_rank", 0)
            base_stub = 6
            stub_step = 5
            exit_stub_y = int(sp[1] + base_stub + src_rank * stub_step)
            entry_stub_y = int(tp[1] - base_stub - tgt_rank * stub_step)

            # =========================================================================
            # LEVEL 1: Intra-Class Routing (LCA = Class Box)
            # Exits bottom stub to right road, enters top stub from right (intra-class exception)
            # =========================================================================
            if sf == tf and s_cls and s_cls == t_cls and s_cls in spkg.get("class_boxes", {}):
                cbox = spkg["class_boxes"][s_cls]
                c_idx = class_rail_counts.get(s_cls, 0)
                class_rail_counts[s_cls] = c_idx + 1
                out_rail_x = cbox["road_out_x"] - (c_idx % 12) * rcfg.class_rail_step
                l["waypoints"] = self._simplify_collinear([
                    int(sp[0]), int(sp[1]),
                    int(sp[0]), exit_stub_y,
                    int(out_rail_x), exit_stub_y,
                    int(out_rail_x), entry_stub_y,
                    int(tp[0]), entry_stub_y,
                    int(tp[0]), int(tp[1]),
                ])
                continue

            # =========================================================================
            # LEVEL 2: Intra-File / Cross-Class Routing (LCA = File Package)
            # Exits bottom stub to right road, bridges across file, enters top stub from left
            # =========================================================================
            if sf == tf:
                f_idx = file_rail_counts.get(sf, 0)
                file_rail_counts[sf] = f_idx + 1
                f_out_x = spkg.get("road_out_x", spkg["x"] + spkg["width"] - 14) - (f_idx % 16) * rcfg.file_rail_step
                f_in_x = spkg.get("road_in_x", spkg["x"] + 14) + (f_idx % 16) * rcfg.file_rail_step
                bridge_y = int((sp[1] + tp[1]) / 2)
                l["waypoints"] = self._simplify_collinear([
                    int(sp[0]), int(sp[1]),
                    int(sp[0]), exit_stub_y,
                    int(f_out_x), exit_stub_y,
                    int(f_out_x), bridge_y,
                    int(f_in_x), bridge_y,
                    int(f_in_x), entry_stub_y,
                    int(tp[0]), entry_stub_y,
                    int(tp[0]), int(tp[1]),
                ])
                continue

            s_zone_id = spkg.get("zone_id", "")
            t_zone_id = tpkg.get("zone_id", "")
            s_col = spkg.get("col_idx", 0)
            t_col = tpkg.get("col_idx", 0)

            sz_meta = zone_hierarchy.get(s_zone_id, {})
            tz_meta = zone_hierarchy.get(t_zone_id, {})

            s_z_min_x = sz_meta.get("x", 0) + 16 if s_zone_id in zone_hierarchy else spkg["x"] - 64
            s_z_max_x = sz_meta.get("x", 0) + sz_meta.get("width", 1000) - 16 if s_zone_id in zone_hierarchy else spkg["x"] + spkg["width"] + 64
            t_z_min_x = tz_meta.get("x", 0) + 16 if t_zone_id in zone_hierarchy else tpkg["x"] - 64
            t_z_max_x = tz_meta.get("x", 0) + tz_meta.get("width", 1000) - 16 if t_zone_id in zone_hierarchy else tpkg["x"] + tpkg["width"] + 64

            s_z_min_y = sz_meta.get("y", 0) + 36
            s_z_max_y = sz_meta.get("y", 0) + sz_meta.get("height", 1000) - 14
            t_z_min_y = tz_meta.get("y", 0) + 36
            t_z_max_y = tz_meta.get("y", 0) + tz_meta.get("height", 1000) - 14

            s_row_hw = spkg.get("row_bottom_highway_y", spkg["y"] + spkg["height"] + 24)
            t_row_hw = tpkg.get("row_bottom_highway_y", tpkg["y"] + tpkg["height"] + 24)

            # Row highway channel bounds: dynamically allocated inter-row channel
            s_row_min_y = spkg.get("row_highway_min_y", s_row_hw - 20)
            s_row_max_y = min(spkg.get("row_highway_max_y", s_row_hw + 24), s_z_max_y)
            if s_row_min_y > s_row_max_y:
                s_row_min_y = s_row_max_y - 8

            t_row_min_y = tpkg.get("row_highway_min_y", t_row_hw - 20)
            t_row_max_y = min(tpkg.get("row_highway_max_y", t_row_hw + 24), t_z_max_y)
            if t_row_min_y > t_row_max_y:
                t_row_min_y = t_row_max_y - 8

            # Multi-lane vertical escape corridor (right of source package, sized dynamically)
            s_out_traffic = pkg_traffic.get(sf, (0, 0))[0]
            escape_w = max(48, (s_out_traffic + 2) * rcfg.track_step)
            base_escape_x = spkg["x"] + spkg["width"] + 14 + (src_rank % 6) * rcfg.track_step
            min_escape_x = spkg["x"] + spkg["width"] + 10
            max_escape_x = max(min_escape_x + 16, min(spkg["x"] + spkg["width"] + escape_w, s_z_max_x))
            s_escape_x = find_clear_v_track(
                base_x=base_escape_x,
                y1=exit_stub_y,
                y2=s_row_hw,
                ignore_fps=(sf,),
                min_x=min_escape_x,
                max_x=max_escape_x,
            )

            # Multi-lane vertical arrival corridor (left of target package, sized dynamically)
            t_in_traffic = pkg_traffic.get(tf, (0, 0))[1]
            entry_w = max(48, (t_in_traffic + 2) * rcfg.track_step)
            base_entry_x = tpkg["x"] - 14 - (tgt_rank % 6) * rcfg.track_step
            max_entry_x = tpkg["x"] - 10
            min_entry_x = min(max_entry_x - 16, max(tpkg["x"] - entry_w, t_z_min_x))
            t_entry_x = find_clear_v_track(
                base_x=base_entry_x,
                y1=t_row_hw,
                y2=entry_stub_y,
                ignore_fps=(tf,),
                min_x=min_entry_x,
                max_x=max_entry_x,
            )

            # =========================================================================
            # LEVEL 3: Intra-Zone / Cross-File Routing (LCA = Folder Zone)
            # Files placed on 2D grid: uses row bottom highways and file side roads
            # Strictly bounded within zone borders
            # =========================================================================
            if s_zone_id == t_zone_id and s_zone_id in zone_hierarchy:
                z_meta = sz_meta
                z_min_y = s_z_min_y
                z_max_y = s_z_max_y
                z_min_x = s_z_min_x
                z_max_x = s_z_max_x

                s_row = spkg.get("grid_row", 0)
                t_row = tpkg.get("grid_row", 0)

                if s_row == t_row:
                    row_min_y = max(s_row_min_y, t_row_min_y)
                    row_max_y = min(s_row_max_y, t_row_max_y)
                    if row_min_y > row_max_y:
                        row_min_y = row_max_y - 8
                    row_hw_y = find_clear_h_track(
                        s_row_hw, s_escape_x, t_entry_x, (sf, tf),
                        min_y=row_min_y, max_y=row_max_y,
                    )
                    l["waypoints"] = self._simplify_collinear([
                        int(sp[0]), int(sp[1]),
                        int(sp[0]), exit_stub_y,
                        int(s_escape_x), exit_stub_y,
                        int(s_escape_x), int(row_hw_y),
                        int(t_entry_x), int(row_hw_y),
                        int(t_entry_x), entry_stub_y,
                        int(tp[0]), entry_stub_y,
                        int(tp[0]), int(tp[1]),
                    ])
                else:
                    sub_buses = z_meta.get("sub_col_buses", [])
                    s_sub_col = spkg.get("sub_col_idx", 0)
                    base_bus_x = (
                        sub_buses[min(s_sub_col, len(sub_buses) - 1)]
                        if sub_buses
                        else z_meta.get("road_out_x", spkg["x"] + spkg["width"] + 48)
                    )
                    s_row_hw_y = find_clear_h_track(
                        s_row_hw, s_escape_x, base_bus_x, (sf,),
                        min_y=s_row_min_y, max_y=s_row_max_y,
                    )
                    t_row_hw_y = find_clear_h_track(
                        t_row_hw, base_bus_x, t_entry_x, (tf,),
                        min_y=t_row_min_y, max_y=t_row_max_y,
                    )
                    v_bus_x = find_clear_v_track(
                        base_bus_x, s_row_hw_y, t_row_hw_y, (),
                        min_x=z_min_x, max_x=z_max_x,
                    )
                    l["waypoints"] = self._simplify_collinear([
                        int(sp[0]), int(sp[1]),
                        int(sp[0]), exit_stub_y,
                        int(s_escape_x), exit_stub_y,
                        int(s_escape_x), int(s_row_hw_y),
                        int(v_bus_x), int(s_row_hw_y),
                        int(v_bus_x), int(t_row_hw_y),
                        int(t_entry_x), int(t_row_hw_y),
                        int(t_entry_x), entry_stub_y,
                        int(tp[0]), entry_stub_y,
                        int(tp[0]), int(tp[1]),
                    ])
                continue

            # =========================================================================
            # LEVEL 4: Intra-Column / Cross-Zone Routing (LCA = Depth Column)
            # Dedicated intra-column highway corridor (strictly separated from cross-col)
            # =========================================================================
            if s_col == t_col:
                col_meta = column_highways.get(s_col, {})
                base_col_hw_x = col_meta.get(
                    "intra_col_highway_x",
                    spkg["x"] + spkg["width"] + getattr(rcfg, "intra_col_highway_offset", 60),
                )
                min_hw_x = col_meta.get("intra_col_min_x", base_col_hw_x - 32)
                max_hw_x = col_meta.get("intra_col_max_x", base_col_hw_x + 64)

                s_row_hw_y = find_clear_h_track(
                    s_row_hw, s_escape_x, base_col_hw_x, (sf,),
                    min_y=s_row_min_y, max_y=s_row_max_y,
                )
                t_row_hw_y = find_clear_h_track(
                    t_row_hw, base_col_hw_x, t_entry_x, (tf,),
                    min_y=t_row_min_y, max_y=t_row_max_y,
                )

                hw_x = find_clear_v_track(
                    base_col_hw_x, s_row_hw_y, t_row_hw_y, (),
                    min_x=min_hw_x, max_x=max_hw_x,
                )
                l["waypoints"] = self._simplify_collinear([
                    int(sp[0]), int(sp[1]),
                    int(sp[0]), exit_stub_y,
                    int(s_escape_x), exit_stub_y,
                    int(s_escape_x), int(s_row_hw_y),
                    int(hw_x), int(s_row_hw_y),
                    int(hw_x), int(t_row_hw_y),
                    int(t_entry_x), int(t_row_hw_y),
                    int(t_entry_x), entry_stub_y,
                    int(tp[0]), entry_stub_y,
                    int(tp[0]), int(tp[1]),
                ])
                continue

            # =========================================================================
            # LEVEL 5: Cross-Column Funnel Routing (LCA = Root Board)
            # Route all inter-column lines through structured Horizontal Trunk Highway (the bridge)
            # Local Row Highway -> Column Departure Highway -> Horizontal Trunk Bridge -> Target Column Arrival Highway -> Target Row Highway
            # =========================================================================
            going_right = t_col > s_col
            s_col_meta = column_highways.get(s_col, {})
            t_col_meta = column_highways.get(t_col, {})

            if going_right:
                base_s_hw_x = s_col_meta.get("right_exit_x", s_col_meta.get("cross_col_exit_x", spkg["x"] + spkg["width"] + 260))
                s_hw_min_x = s_col_meta.get("right_exit_min_x", s_col_meta.get("cross_col_min_x", base_s_hw_x - 40))
                s_hw_max_x = s_col_meta.get("right_exit_max_x", s_col_meta.get("cross_col_max_x", base_s_hw_x + 100))
                base_t_hw_x = t_col_meta.get("left_entry_x", t_col_meta.get("cross_col_entry_x", tpkg["x"] - 96))
                t_hw_min_x = t_col_meta.get("left_entry_min_x", t_col_meta.get("cross_col_entry_min_x", base_t_hw_x - 64))
                t_hw_max_x = t_col_meta.get("left_entry_max_x", t_col_meta.get("cross_col_entry_max_x", base_t_hw_x + 64))
            else:
                base_s_hw_x = s_col_meta.get("left_exit_x", s_col_meta.get("cross_col_left_exit_x", spkg["x"] - 260))
                s_hw_min_x = s_col_meta.get("left_exit_min_x", s_col_meta.get("cross_col_left_min_x", base_s_hw_x - 100))
                s_hw_max_x = s_col_meta.get("left_exit_max_x", s_col_meta.get("cross_col_left_max_x", base_s_hw_x + 40))
                base_t_hw_x = t_col_meta.get("right_entry_x", t_col_meta.get("cross_col_right_entry_x", tpkg["x"] + tpkg["width"] + 360))
                t_hw_min_x = t_col_meta.get("right_entry_min_x", base_t_hw_x - 64)
                t_hw_max_x = t_col_meta.get("right_entry_max_x", base_t_hw_x + 64)

            s_row_hw_y = find_clear_h_track(
                s_row_hw, s_escape_x, base_s_hw_x, (sf,),
                min_y=s_row_min_y, max_y=s_row_max_y,
            )
            t_row_hw_y = find_clear_h_track(
                t_row_hw, base_t_hw_x, t_entry_x, (tf,),
                min_y=t_row_min_y, max_y=t_row_max_y,
            )

            # Choose nearest horizontal trunk bridge to link's vertical midpoint
            ideal_bridge_y = (s_row_hw_y + t_row_hw_y) / 2.0
            base_trunk_y = min(trunk_highways, key=lambda th: abs(th - ideal_bridge_y))

            # Allocate horizontal trunk track across columns
            bridge_min_x = min(base_s_hw_x, base_t_hw_x)
            bridge_max_x = max(base_s_hw_x, base_t_hw_x)
            trunk_y = find_clear_h_track(base_trunk_y, bridge_min_x, bridge_max_x, ())

            # Source vertical departure highway: travels vertically from s_row_hw_y to trunk_y
            s_hw_x = find_clear_v_track(
                base_s_hw_x, s_row_hw_y, trunk_y, (),
                min_x=s_hw_min_x, max_x=s_hw_max_x,
            )

            # Target vertical arrival highway: travels vertically from trunk_y to t_row_hw_y
            t_hw_x = find_clear_v_track(
                base_t_hw_x, trunk_y, t_row_hw_y, (),
                min_x=t_hw_min_x, max_x=t_hw_max_x,
            )

            # Claim bridge horizontal span with actual allocated vertical highway X coordinates
            claim_interval(claimed_h_tracks, trunk_y, min(s_hw_x, t_hw_x), max(s_hw_x, t_hw_x))

            l["waypoints"] = self._simplify_collinear([
                int(sp[0]), int(sp[1]),
                int(sp[0]), exit_stub_y,
                int(s_escape_x), exit_stub_y,
                int(s_escape_x), int(s_row_hw_y),
                int(s_hw_x), int(s_row_hw_y),
                int(s_hw_x), int(trunk_y),
                int(t_hw_x), int(trunk_y),
                int(t_hw_x), int(t_row_hw_y),
                int(t_entry_x), int(t_row_hw_y),
                int(t_entry_x), entry_stub_y,
                int(tp[0]), entry_stub_y,
                int(tp[0]), int(tp[1]),
            ])
