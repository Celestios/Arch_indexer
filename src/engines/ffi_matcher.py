import re
from dataclasses import dataclass
from typing import List, Optional
from engines.ffi_extractor import FfiSurface


@dataclass
class FfiMatch:
    source_symbol: str
    target_symbol: str
    confidence: float
    match_type: str  # "name" or "name+signature"


class FfiMatcher:
    """
    Matches FFI surfaces across languages by name + signature.
    """

    def match(self, surfaces_a: List[FfiSurface], surfaces_b: List[FfiSurface]) -> List[FfiMatch]:
        matches = []

        if surfaces_a and surfaces_b and surfaces_a[0].language == surfaces_b[0].language:
            return matches

        name_to_a = {}
        for s in surfaces_a:
            name_to_a.setdefault(s.symbol_name, []).append(s)

        name_to_b = {}
        for s in surfaces_b:
            name_to_b.setdefault(s.symbol_name, []).append(s)

        for name in name_to_a:
            if name not in name_to_b:
                continue

            group_a = name_to_a[name]
            group_b = name_to_b[name]

            if len(group_a) == 1 and len(group_b) == 1:
                sig_a = self._normalize_signature(group_a[0].signature)
                sig_b = self._normalize_signature(group_b[0].signature)
                if sig_a and sig_b and self._signatures_compatible(sig_a, sig_b):
                    matches.append(FfiMatch(
                        source_symbol=self._symbol_id(group_a[0]),
                        target_symbol=self._symbol_id(group_b[0]),
                        confidence=1.0,
                        match_type="name+signature"
                    ))
                else:
                    matches.append(FfiMatch(
                        source_symbol=self._symbol_id(group_a[0]),
                        target_symbol=self._symbol_id(group_b[0]),
                        confidence=0.8,
                        match_type="name"
                    ))
            else:
                matched_b_indices = set()
                for sa in group_a:
                    sig_a = self._normalize_signature(sa.signature)
                    best_match = None
                    for j, sb in enumerate(group_b):
                        if j in matched_b_indices:
                            continue
                        sig_b = self._normalize_signature(sb.signature)
                        if sig_a and sig_b and self._signatures_compatible(sig_a, sig_b):
                            best_match = (j, sb)
                            break
                    if best_match:
                        j, sb = best_match
                        matched_b_indices.add(j)
                        matches.append(FfiMatch(
                            source_symbol=self._symbol_id(sa),
                            target_symbol=self._symbol_id(sb),
                            confidence=1.0,
                            match_type="name+signature"
                        ))

        return matches

    def _symbol_id(self, surface: FfiSurface) -> str:
        return f"{surface.language}::{surface.filepath}::{surface.symbol_name}"

    def _normalize_signature(self, sig: str) -> str:
        if not sig:
            return ""
        normalized = re.sub(r'\s+', ' ', sig.strip().lower())
        return normalized

    def _signatures_compatible(self, sig_a: str, sig_b: str) -> bool:
        return sig_a == sig_b


