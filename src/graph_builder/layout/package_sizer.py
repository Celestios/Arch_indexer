"""
Package Sizer & Internal Component Placer.
Driven by centralized SizerConfig; registers explicit class bounding boxes and
file/zone/column lineage on every symbol node for LCA hierarchical routing.
"""

import os
from typing import Dict, List, Any, Optional, Tuple
from ..config import CircuitConfig, SizerConfig


class PackageSizer:
    """
    Computes collision-free bounding boxes for File Packages, nested Class enclosures,
    and Symbol chips using centralized SizerConfig parameters.
    """

    def __init__(self, grid_size: int = 8, sizer_cfg: Optional[SizerConfig] = None):
        self.grid_size = grid_size
        self.cfg = sizer_cfg or SizerConfig()

    def snap(self, val: float) -> int:
        return int(round(val / self.grid_size) * self.grid_size)

    def measure_port_gutters(self, symbols: List[Dict[str, Any]]) -> Dict[str, float]:
        max_in_chars = 0
        max_out_chars = 0

        for s in symbols:
            ports = s.get("ports") or {}
            for inp in ports.get("inputs") or []:
                name = inp.get("name", "")
                if name and name not in ("self", "cls"):
                    max_in_chars = max(max_in_chars, len(name))
            out_type = ports.get("output")
            if out_type:
                max_out_chars = max(max_out_chars, len(str(out_type)) + 3)

        c = self.cfg
        left_gutter = (
            min(c.max_port_gutter, max(c.min_port_gutter, max_in_chars * c.char_px_port + c.port_clearance_px))
            if max_in_chars > 0
            else c.default_port_gutter
        )
        right_gutter = (
            min(c.max_port_gutter, max(c.min_port_gutter, max_out_chars * c.char_px_port + c.port_clearance_px))
            if max_out_chars > 0
            else c.default_port_gutter
        )
        return {
            "left_gutter": left_gutter,
            "right_gutter": right_gutter,
        }

    def compute_package_blueprint(
        self,
        filepath: str,
        pkg_meta: Dict[str, Any],
        syms: List[Dict[str, Any]],
        zone_idx: int,
        zone_color: str,
        node_edge_counts: Optional[Dict[str, Tuple[int, int]]] = None,
    ) -> Dict[str, Any]:
        c = self.cfg
        class_nodes = [s for s in syms if s.get("type") == "class"]
        class_id_set = {cl["id"] for cl in class_nodes}

        gutters = self.measure_port_gutters(syms)
        left_gutter = self.snap(gutters["left_gutter"])
        right_gutter = self.snap(gutters["right_gutter"])

        max_label_len = max([len(s.get("label", "")) for s in syms] + [16])
        chip_w = self.snap(min(c.max_chip_w, max(c.min_chip_w, max_label_len * c.char_px_label + 28.0)))

        def _calc_sym_row_h(sid: str) -> Tuple[float, float, float]:
            in_c, out_c = node_edge_counts.get(sid, (0, 0)) if node_edge_counts else (0, 0)
            top_space = max(8.0, in_c * 5.0)
            bottom_space = max(8.0, out_c * 5.0)
            return top_space, bottom_space, top_space + 20.0 + bottom_space

        class_blueprints = []
        for cl in class_nodes:
            members = [s for s in syms if s.get("parent_class") == cl["id"]]
            members.sort(
                key=lambda m: (
                    0 if m.get("type") == "constructor" else (1 if m.get("type") == "method" else 2),
                    m.get("label", ""),
                )
            )
            cl["members"] = members
            cw = self.snap(left_gutter + chip_w + right_gutter + c.class_rail_margin)
            members_h = sum(_calc_sym_row_h(m["id"])[2] for m in members) if members else c.member_row_h
            ch = self.snap(c.class_header_h + members_h + c.class_padding_bottom)
            class_blueprints.append(
                {
                    "class_node": cl,
                    "width": cw,
                    "height": ch,
                    "chip_w": chip_w,
                    "left_gutter": left_gutter,
                    "right_gutter": right_gutter,
                }
            )

        top_syms = [
            s for s in syms if s["id"] not in class_id_set and s.get("parent_class") not in class_id_set
        ]
        top_syms.sort(key=lambda s: (0 if s.get("type") == "function" else 1, s.get("label", "")))

        inner_w = max(
            [cb["width"] for cb in class_blueprints]
            + [left_gutter + chip_w + right_gutter + c.class_rail_margin, c.min_pkg_w]
        )
        pkg_w = self.snap(inner_w + c.pkg_side_channel_w)

        classes_total_h = sum(cb["height"] + 16.0 for cb in class_blueprints)
        top_total_h = (sum(_calc_sym_row_h(s["id"])[2] for s in top_syms) + 16.0) if top_syms else 0.0
        pkg_h = self.snap(max(c.min_pkg_h, 24.0 + classes_total_h + top_total_h + 16.0))

        filename = pkg_meta.get("filename") or os.path.basename(filepath)
        tab_w = self.snap(min(pkg_w - 16.0, max(96.0, len(filename) * 7.5 + 28.0)))

        return {
            "filepath": filepath,
            "filename": filename,
            "pkg_meta": pkg_meta,
            "width": pkg_w,
            "height": pkg_h,
            "tab_w": tab_w,
            "chip_w": chip_w,
            "left_gutter": left_gutter,
            "right_gutter": right_gutter,
            "class_blueprints": class_blueprints,
            "top_syms": top_syms,
            "zone": zone_idx,
            "color": zone_color,
            "node_edge_counts": node_edge_counts or {},
        }

    def instantiate_package(
        self,
        blueprint: Dict[str, Any],
        pkg_x: int,
        pkg_y: int,
        zone_id: str = "",
        col_idx: int = 0,
        sub_col_idx: int = 0,
    ) -> Dict[str, Any]:
        c = self.cfg
        pkg_w = blueprint["width"]
        pkg_h = blueprint["height"]
        chip_w = blueprint["chip_w"]
        left_gutter = blueprint["left_gutter"]
        z_idx = blueprint["zone"]

        pkg_info = {
            "id": blueprint["filepath"],
            "filepath": blueprint["filepath"],
            "filename": blueprint["filename"],
            "language": blueprint["pkg_meta"].get("language", "python"),
            "status": blueprint["pkg_meta"].get("status", "COMPLIANT"),
            "x": pkg_x,
            "y": pkg_y,
            "width": pkg_w,
            "height": pkg_h,
            "tab_x": pkg_x,
            "tab_y": pkg_y - 20,
            "tab_w": blueprint["tab_w"],
            "tab_h": 20,
            "zone": z_idx,
            "zone_id": zone_id,
            "col_idx": col_idx,
            "sub_col_idx": sub_col_idx,
            "color": blueprint["color"],
            "classes": [],
            "class_boxes": {},
        }

        node_edge_counts = blueprint.get("node_edge_counts", {})

        def _calc_sym_row_h(sid: str) -> Tuple[float, float, float]:
            in_c, out_c = node_edge_counts.get(sid, (0, 0)) if node_edge_counts else (0, 0)
            top_space = max(8.0, in_c * 5.0)
            bottom_space = max(8.0, out_c * 5.0)
            return top_space, bottom_space, top_space + 20.0 + bottom_space

        inner_y = pkg_y + 22
        for cb in blueprint["class_blueprints"]:
            cl = cb["class_node"]
            cw = cb["width"]
            ch = cb["height"]
            cx = self.snap(pkg_x + (pkg_w - cw) / 2)
            cy = self.snap(inner_y)
            chip_center_x = self.snap(cx + 16 + left_gutter + chip_w / 2)

            cl["x"] = chip_center_x
            cl["y"] = self.snap(cy + 16)
            cl["width"] = chip_w
            cl["height"] = 20
            cl["component_type"] = "CLASS_BOX"
            cl["zone"] = z_idx
            cl["zone_id"] = zone_id
            cl["col_idx"] = col_idx
            cl["class_box_id"] = cl["id"]

            cls_box = {
                "id": cl["id"],
                "label": cl.get("label", ""),
                "x": cx,
                "y": cy,
                "width": cw,
                "height": ch,
                "road_in_x": self.snap(cx + 12),
                "road_out_x": self.snap(cx + cw - 12),
            }
            pkg_info["classes"].append(cls_box)
            pkg_info["class_boxes"][cl["id"]] = cls_box

            mem_y = cy + 34
            for m in cl["members"]:
                top_space, bottom_space, row_h = _calc_sym_row_h(m["id"])
                chip_y = self.snap(mem_y + top_space + 10)
                m["x"] = chip_center_x
                m["y"] = chip_y
                m["width"] = chip_w
                m["height"] = 20
                m["top_space"] = top_space
                m["bottom_space"] = bottom_space
                m["component_type"] = "METHOD_BOX"
                m["zone"] = z_idx
                m["zone_id"] = zone_id
                m["col_idx"] = col_idx
                m["class_box_id"] = cl["id"]
                m["in_pin"] = (chip_center_x, self.snap(chip_y - 10))
                m["out_pin"] = (chip_center_x, self.snap(chip_y + 10))
                m["class_road_in_x"] = self.snap(cx + 12)
                m["class_road_out_x"] = self.snap(cx + cw - 12)
                m["pkg_road_in_x"] = self.snap(pkg_x + 14)
                m["pkg_road_out_x"] = self.snap(pkg_x + pkg_w - 14)
                mem_y += int(row_h)

            inner_y += ch + 16

        if blueprint["top_syms"]:
            chip_center_x = self.snap(pkg_x + 24 + left_gutter + chip_w / 2)
            top_y = inner_y + 6
            for s in blueprint["top_syms"]:
                top_space, bottom_space, row_h = _calc_sym_row_h(s["id"])
                chip_y = self.snap(top_y + top_space + 10)
                s["x"] = chip_center_x
                s["y"] = chip_y
                s["width"] = chip_w
                s["height"] = 20
                s["top_space"] = top_space
                s["bottom_space"] = bottom_space
                s["component_type"] = "FN_BOX"
                s["zone"] = z_idx
                s["zone_id"] = zone_id
                s["col_idx"] = col_idx
                s["class_box_id"] = None
                s["in_pin"] = (chip_center_x, self.snap(chip_y - 10))
                s["out_pin"] = (chip_center_x, self.snap(chip_y + 10))
                s["class_road_in_x"] = self.snap(pkg_x + 14)
                s["class_road_out_x"] = self.snap(pkg_x + pkg_w - 14)
                s["pkg_road_in_x"] = self.snap(pkg_x + 14)
                s["pkg_road_out_x"] = self.snap(pkg_x + pkg_w - 14)
                top_y += int(row_h)

        pkg_info["road_in_x"] = self.snap(pkg_x + 14)
        pkg_info["road_out_x"] = self.snap(pkg_x + pkg_w - 14)

        return pkg_info
