import hashlib


def generate_violation_id(*parts: str) -> str:
    """Generate a deterministic 16-char hex violation ID from the given parts."""
    combined = "|".join(str(p) for p in parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
