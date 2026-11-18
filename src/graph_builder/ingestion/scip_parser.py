"""
SCIP Symbol and Callable Signature Parser.
Universal and repository-agnostic (no hardcoded project names).
"""

import re
from typing import Dict, Any, Optional, Set


class ScipParser:
    """
    Parses SCIP symbol strings and Python/TypeScript/Rust callable signatures
    into structured components and directional data-flow ports.
    """

    @staticmethod
    def parse_signature_ports(
        docstring: Optional[str] = None,
        signature_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Parses callable signature strings into ordered input parameters (excluding self/cls)
        and a single return output type.
        """
        text = signature_str or ""
        if not text and docstring:
            if "```python" in docstring:
                text = docstring.split("```python", 1)[1].split("```", 1)[0].strip()
            elif "```" in docstring:
                text = docstring.split("```", 1)[1].split("```", 1)[0].strip()

        if not text:
            return {"inputs": [], "output": None}

        first_paren = text.find("(")
        if first_paren == -1:
            return {"inputs": [], "output": None}

        last_paren = text.rfind(")")
        if last_paren == -1 or last_paren <= first_paren:
            return {"inputs": [], "output": None}

        raw_params = text[first_paren + 1:last_paren].strip()
        after_paren = text[last_paren + 1:].strip()

        ret_type = None
        if "->" in after_paren:
            ret_part = after_paren.split("->", 1)[1].strip().rstrip(":")
            ret_type = ret_part.strip() or None

        inputs = []
        if raw_params:
            tokens = []
            cur = []
            depth = 0
            for char in raw_params:
                if char in "([{":
                    depth += 1
                    cur.append(char)
                elif char in ")]}":
                    depth -= 1
                    cur.append(char)
                elif char == "," and depth == 0:
                    tokens.append("".join(cur).strip())
                    cur = []
                else:
                    cur.append(char)
            if cur:
                tokens.append("".join(cur).strip())

            for token in tokens:
                if not token or token in ("/", "*"):
                    continue
                parts = token.split("=", 1)
                decl = parts[0].strip()
                if ":" in decl:
                    p_name, p_type = decl.split(":", 1)
                    p_name = p_name.strip()
                    p_type = p_type.strip()
                else:
                    p_name = decl.strip()
                    p_type = "Any"

                # Omit implicit instance/class receivers from data-flow input pins
                if p_name in ("self", "cls"):
                    continue

                inputs.append({
                    "name": p_name,
                    "type": p_type,
                })

        return {"inputs": inputs, "output": ret_type}

    @staticmethod
    @staticmethod
    def parse_scip_symbol(
        symbol_str: str,
        filepath: Optional[str] = None,
        known_files: Optional[Set[str]] = None,
        clean_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Parses a SCIP symbol string into structured components without hardcoded repo names.
        Determines `is_external` dynamically based on workspace file membership.
        Cleanly extracts short `label` stripping dot-separated module paths.
        """
        if not symbol_str:
            return {
                "raw": "",
                "label": "unknown",
                "display_name": "unknown",
                "pkg": "",
                "version": "",
                "descriptor": "",
                "is_local": False,
                "is_external": False,
                "is_parameter": False,
            }

        symbol_str = symbol_str.strip()

        if symbol_str.startswith("local "):
            return {
                "raw": symbol_str,
                "label": symbol_str,
                "display_name": symbol_str,
                "pkg": "local",
                "version": "",
                "descriptor": symbol_str,
                "is_local": True,
                "is_external": False,
                "is_parameter": False,
            }

        is_parameter = bool("().(" in symbol_str and symbol_str.endswith(")"))

        parts = symbol_str.split(" ")
        if len(parts) >= 4:
            pkg = parts[2]
            version = parts[3]
            desc = " ".join(parts[4:]) if len(parts) > 4 else parts[-1]
            clean_desc = desc.replace("`", "")

            # Universal external detection:
            # 1. If known_files is provided, symbol is internal if its filepath is in known_files.
            # 2. Otherwise, check if pkg is stdlib/builtin or lacks a workspace filepath.
            norm_fp = filepath.replace("\\", "/") if filepath else None
            if known_files is not None and norm_fp:
                is_external = norm_fp not in known_files
            else:
                is_external = "stdlib" in pkg.lower() or "builtin" in pkg.lower() or (norm_fp is None and pkg not in (".", ""))

            display_name = clean_desc.rstrip("#/.")
            if clean_desc.endswith("()."):
                base = clean_desc[:-3].rstrip("#/.")
                segments = re.split(r"[/:#.]", base)
                short_name = segments[-1] + "()"
            else:
                segments = re.split(r"[/:#.]", display_name)
                short_name = segments[-1] if segments else display_name

            short_name = re.sub(r"\.\([a-zA-Z0-9_]+\)$", "", short_name)
            if "#" in short_name:
                short_name = short_name.split("#")[-1]
            if "." in short_name and not short_name.endswith("()"):
                short_name = short_name.split(".")[-1]
            elif "." in short_name and short_name.endswith("()"):
                short_name = short_name[:-2].split(".")[-1] + "()"

            return {
                "raw": symbol_str,
                "label": short_name or clean_desc,
                "display_name": display_name,
                "pkg": pkg,
                "version": version,
                "descriptor": clean_desc,
                "is_local": False,
                "is_external": is_external,
                "is_parameter": is_parameter,
            }

        source_text = clean_symbol or symbol_str
        cleaned = source_text.replace("`", "").rstrip("#/.")
        has_parens = cleaned.endswith("()") or cleaned.endswith("().")
        base = cleaned[:-3] if cleaned.endswith("().") else (cleaned[:-2] if cleaned.endswith("()") else cleaned)
        leaf = re.split(r"[/:\\.#]", base)[-1]
        label = (leaf + "()") if has_parens else leaf
        return {
            "raw": symbol_str,
            "label": label or symbol_str,
            "display_name": cleaned,
            "pkg": "",
            "version": "",
            "descriptor": symbol_str,
            "is_local": False,
            "is_external": False,
            "is_parameter": is_parameter,
        }
