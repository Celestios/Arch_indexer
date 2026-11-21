from typing import List, Union


def validate_filepaths(filepaths: Union[List[str], str]) -> List[str]:
    """Normalize and parse filepaths from various input formats."""
    if isinstance(filepaths, str):
        if "," in filepaths:
            return [p.strip() for p in filepaths.split(",") if p.strip()]
        return [filepaths.strip()]
    return list(filepaths)


def validate_direction(direction: str) -> tuple[bool, str]:
    """Validate compile_context direction parameter. Returns (is_valid, value_or_error)."""
    direction = direction.lower()
    if direction not in ("upstream", "downstream", "both"):
        return False, f"Invalid direction: '{direction}'. Allowed: upstream, downstream, both."
    return True, direction


def validate_resolution(resolution: str) -> tuple[bool, str]:
    """Validate compile_context resolution parameter. Returns (is_valid, value_or_error)."""
    resolution = resolution.lower()
    if resolution not in ("full", "signature"):
        return False, f"Invalid resolution: '{resolution}'. Allowed: full, signature."
    return True, resolution
