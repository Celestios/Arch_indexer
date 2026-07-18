import hashlib


class ViolationId:
    """Generates unique, deterministic violation IDs from violation attributes."""

    @staticmethod
    def generate(*parts: str) -> str:
        """
        Generate a deterministic violation ID from the given parts.

        Args:
            *parts: Variable number of strings to hash

        Returns:
            SHA-256 hash truncated to 16 hex characters
        """
        combined = "|".join(str(p) for p in parts)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]
