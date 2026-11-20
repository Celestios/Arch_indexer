"""
Centralized Configuration Loader for the Hierarchical Funnel PCB Layout & Router.
Loads defaults and merges user overrides from a JSON file.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List


@dataclass
class LayoutConfig:
    board_margin_x: int = 120
    board_margin_y: int = 140
    column_highway_w: int = 560
    zone_margin_y: int = 80
    zone_padding_x: int = 64
    zone_padding_top: int = 56
    zone_padding_bottom: int = 64
    chip_margin_x: int = 144
    chip_margin_y: int = 80
    zone_grid_threshold: int = 2
    zone_max_cols: int = 5
    zone_target_aspect_ratio: float = 2.0
    align_zone_in_subtree: str = "center"  # "top" or "center"


@dataclass
class SizerConfig:
    char_px_port: float = 5.6
    port_clearance_px: float = 18.0
    min_port_gutter: float = 28.0
    max_port_gutter: float = 130.0
    default_port_gutter: float = 24.0
    char_px_label: float = 7.2
    min_chip_w: float = 168.0
    max_chip_w: float = 260.0
    member_row_h: float = 30.0
    class_header_h: float = 34.0
    class_padding_bottom: float = 14.0
    class_rail_margin: float = 32.0
    pkg_side_channel_w: float = 48.0
    min_pkg_w: float = 260.0
    min_pkg_h: float = 72.0


@dataclass
class RoutingConfig:
    track_step: int = 8
    track_snap: int = 4
    lane_clearance: int = 6
    pin_escape_dy: int = 6
    hub_stub_length: int = 22
    class_rail_inset: int = 8
    class_rail_step: int = 4
    file_rail_inset: int = 10
    file_rail_step: int = 5
    zone_bus_offset: int = 72
    col_highway_offset: int = 36
    intra_col_highway_offset: int = 60
    cross_col_highway_offset: int = 260
    cross_col_entry_offset: int = 96
    trunk_highway_mode: str = "spaced"  # "center" (single bridge at center) or "spaced" (multiple bridges)
    trunk_highway_spacing: int = 4800
    trunk_highway_count: int = 3
    trunk_highway_positions: List[int] = field(default_factory=list)


@dataclass
class CircuitConfig:
    grid_size: int = 8
    hub_threshold: int = 6
    max_refs_per_symbol: int = 5
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    sizer: SizerConfig = field(default_factory=SizerConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "CircuitConfig":
        cfg = cls()
        target_path = config_path
        if not target_path:
            packaged_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "circuit_config.json")
            for cand in ("circuit_config.json", os.path.join(".arch", "circuit_config.json"), packaged_cfg):
                if os.path.exists(cand):
                    target_path = cand
                    break

        if target_path and os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                raw: Dict[str, Any] = json.load(f)
            if "grid_size" in raw:
                cfg.grid_size = int(raw["grid_size"])
            if "hub_threshold" in raw:
                cfg.hub_threshold = int(raw["hub_threshold"])
            if "max_refs_per_symbol" in raw:
                cfg.max_refs_per_symbol = int(raw["max_refs_per_symbol"])
            if "layout" in raw and isinstance(raw["layout"], dict):
                for k, v in raw["layout"].items():
                    if hasattr(cfg.layout, k):
                        setattr(cfg.layout, k, v)
            if "sizer" in raw and isinstance(raw["sizer"], dict):
                for k, v in raw["sizer"].items():
                    if hasattr(cfg.sizer, k):
                        setattr(cfg.sizer, k, v)
            if "routing" in raw and isinstance(raw["routing"], dict):
                for k, v in raw["routing"].items():
                    if hasattr(cfg.routing, k):
                        setattr(cfg.routing, k, v)
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
