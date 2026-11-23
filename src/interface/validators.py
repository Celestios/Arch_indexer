import json
from typing import List, Optional, Tuple, Union

VALID_HISTORY_SECTIONS = (
    "hotspots",
    "thrash",
    "coupling",
    "archaeology",
    "growth",
    "test_gap",
)


def validate_filepaths(filepaths: Union[List[str], str]) -> List[str]:
    """Normalize and parse filepaths from various input formats."""
    if isinstance(filepaths, str):
        if "," in filepaths:
            return [p.strip() for p in filepaths.split(",") if p.strip()]
        return [filepaths.strip()]
    return list(filepaths)


def validate_direction(direction: str) -> Tuple[bool, str]:
    """Validate compile_context/impact direction parameter. Returns (is_valid, value_or_error)."""
    direction = direction.lower()
    if direction not in ("upstream", "downstream", "both"):
        return False, f"Invalid direction: '{direction}'. Allowed: upstream, downstream, both."
    return True, direction


def validate_resolution(resolution: str) -> Tuple[bool, str]:
    """Validate compile_context resolution parameter. Returns (is_valid, value_or_error)."""
    resolution = resolution.lower()
    if resolution not in ("full", "signature"):
        return False, f"Invalid resolution: '{resolution}'. Allowed: full, signature."
    return True, resolution


def validate_sections(
    sections: Optional[Union[List[str], str]],
    has_target: bool = False,
) -> Tuple[bool, Union[List[str], str]]:
    """
    Normalize and validate `history` sections parameter.
    Returns (True, normalized_list) or (False, error_message).
    """
    if sections is None:
        return True, ["archaeology", "coupling"] if has_target else ["hotspots", "coupling"]

    if isinstance(sections, str):
        stripped = sections.strip()
        if stripped.startswith("["):
            try:
                loaded = json.loads(stripped)
                if isinstance(loaded, list):
                    raw_list = [str(s).strip().lower() for s in loaded if str(s).strip()]
                else:
                    raw_list = [stripped.lower()]
            except Exception:
                raw_list = [s.strip().lower() for s in stripped.split(",") if s.strip()]
        else:
            raw_list = [s.strip().lower() for s in stripped.split(",") if s.strip()]
    elif isinstance(sections, (list, tuple, set)):
        raw_list = [str(s).strip().lower() for s in sections if str(s).strip()]
    else:
        return False, f"Invalid sections type. Allowed values: {', '.join(VALID_HISTORY_SECTIONS)}."

    if not raw_list:
        return True, ["archaeology", "coupling"] if has_target else ["hotspots", "coupling"]

    deduped: List[str] = []
    invalid: List[str] = []
    for item in raw_list:
        if item not in VALID_HISTORY_SECTIONS:
            invalid.append(item)
        elif item not in deduped:
            deduped.append(item)

    if invalid:
        return (
            False,
            f"Invalid section(s): {', '.join(invalid)}. Allowed: {', '.join(VALID_HISTORY_SECTIONS)}.",
        )

    return True, deduped


VALID_CLUSTER_VIEWS = ("tree", "mermaid", "both")
VALID_CLUSTER_UNITS = ("symbol", "file")


def validate_cluster_view(view: Optional[str]) -> Tuple[bool, str]:
    """Validate cluster view parameter ('tree', 'mermaid', 'both'). Returns (is_valid, value_or_error)."""
    v = (view or "both").strip().lower()
    if v not in VALID_CLUSTER_VIEWS:
        return False, f"Invalid view: '{view}'. Allowed: {', '.join(VALID_CLUSTER_VIEWS)}."
    return True, v


def validate_cluster_unit(unit: Optional[str]) -> Tuple[bool, str]:
    """Validate cluster unit parameter ('symbol', 'file'). Returns (is_valid, value_or_error)."""
    u = (unit or "symbol").strip().lower()
    if u not in VALID_CLUSTER_UNITS:
        return False, f"Invalid unit: '{unit}'. Allowed: {', '.join(VALID_CLUSTER_UNITS)}."
    return True, u
