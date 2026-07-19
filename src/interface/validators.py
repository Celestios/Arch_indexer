from typing import Optional, List, Union

from utils.helpers import resolve_filepath


def validate_filepaths(filepaths: Union[List[str], str]) -> List[str]:
    """Normalize and parse filepaths from various input formats."""
    if isinstance(filepaths, str):
        if "," in filepaths:
            return [p.strip() for p in filepaths.split(",") if p.strip()]
        else:
            return [filepaths.strip()]
    return list(filepaths)
