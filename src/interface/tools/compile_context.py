from pathlib import Path
from typing import Optional

from auditor.compiler import ContextCompiler


def handle_compile_context(
    symbol: str,
    radius: int,
    direction: str,
    resolution: str,
    out_filepath: Optional[str],
    repository,
    project_root: Path,
    max_tokens: int = 4000,
) -> str:
    """Compile a deterministic markdown context document. Returns markdown."""
    compiler = ContextCompiler(repository, project_root)
    return compiler.compile(
        focal_symbol=symbol,
        radius=radius,
        direction=direction,
        resolution=resolution,
        out_filepath=out_filepath,
        max_tokens=max_tokens,
    )
