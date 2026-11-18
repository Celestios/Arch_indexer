"""
Tree-sitter AST intelligence engine for Arch-mcp.
Provides sub-2ms syntactic declaration extraction, multi-line signatures, docstrings,
skeleton folding, structural metrics, and syntax rule checks.
"""
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Set
import hashlib
import re

from engines.treesitter.loader import TreesitterLoader
from engines.treesitter.extractor import TreesitterExtractor, SymbolDeclaration
from engines.treesitter.folding import CodeFolder
from engines.treesitter.rules import StructuralRuleChecker
from engines.treesitter.metrics import MetricsCalculator
from engines.treesitter.control_flow import ControlFlowAnalyzer
from engines.treesitter.types_extractor import TypesExtractor


class TreesitterEngine:
    """Unified AST engine facade."""

    @classmethod
    def extract_symbols(
        cls,
        filepath: Union[str, Path],
        source: Optional[Union[str, bytes]] = None,
        project_root: Optional[Path] = None,
    ) -> List[SymbolDeclaration]:
        """Extract all symbol declarations from a file."""
        return TreesitterExtractor.extract_symbols_from_file(filepath, source, project_root)

    @classmethod
    def fold_code(cls, source: Union[str, bytes], language: str) -> str:
        """Fold function/method bodies into '...' preserving signatures and docstrings."""
        return CodeFolder.fold_code(source, language)

    @classmethod
    def check_rules(
        cls,
        filepath: Union[str, Path],
        source: Optional[Union[str, bytes]] = None,
    ) -> List[Dict[str, Any]]:
        """Check for structural anti-patterns (bare excepts, .unwrap(), etc.)."""
        fp = Path(filepath)
        lang = TreesitterLoader.detect_language(fp)
        if not lang:
            return []
        if source is None:
            if not fp.exists():
                return []
            source = fp.read_bytes()
        return StructuralRuleChecker.check_file(fp, source, lang)

    @classmethod
    def sync_file_to_db(
        cls,
        repository,
        filepath: Union[str, Path],
        source: Optional[Union[str, bytes]] = None,
        project_root: Optional[Path] = None,
    ) -> List[SymbolDeclaration]:
        """
        Fast Tier 1 synchronization (< 2ms):
        Extracts AST declarations and updates DuckDB 'symbols' and 'occurrences' (definitions).
        Preserves existing SCIP symbol primary keys and edges if present.
        """
        fp = Path(filepath)
        if project_root:
            try:
                norm_fp = str(fp.resolve().relative_to(Path(project_root).resolve())).replace("\\", "/")
            except Exception:
                norm_fp = str(filepath).replace("\\", "/")
        else:
            norm_fp = str(filepath).replace("\\", "/")

        norm_fp = norm_fp.replace("\\", "/")
        if norm_fp.startswith("./"):
            norm_fp = norm_fp[2:]

        if source is None:
            if not fp.exists():
                return []
            code_bytes = fp.read_bytes()
        elif isinstance(source, str):
            code_bytes = source.encode("utf-8")
        else:
            code_bytes = source

        declarations = cls.extract_symbols(fp, code_bytes, project_root=project_root)
        if not declarations:
            return []

        # 1. Update file hash in files table
        sha256_hash = hashlib.sha256(code_bytes).hexdigest()
        lang = TreesitterLoader.detect_language(fp) or "unknown"
        repository.files.upsert_file(norm_fp, sha256_hash, lang)

        # 2. Get existing symbols in DB for this file to reconcile SCIP IDs
        query_paths = [norm_fp]
        try:
            abs_fp = str(fp.resolve()).replace("\\", "/")
            if abs_fp != norm_fp:
                query_paths.append(abs_fp)
        except Exception:
            pass
        existing = repository.symbols.get_symbols_by_filepaths(query_paths)
        clean_to_existing: Dict[str, str] = {}
        for sym_id, data in existing.items():
            c_sym = data.get("clean_symbol") or sym_id
            clean_to_existing[c_sym] = sym_id

        # Also get existing definition occurrences for this file to reconcile by line
        line_to_existing: Dict[int, str] = {}
        occ_list: List[tuple] = []
        with repository.db_conn.session() as conn:
            occ_rows = conn.execute(
                "SELECT symbol, start_line FROM occurrences WHERE (replace(filepath, '\\', '/') = ? OR filepath = ?) AND (role & 1) != 0",
                (norm_fp, norm_fp)
            ).fetchall()
            for r in occ_rows:
                line_to_existing[r[1]] = r[0]
                occ_list.append((r[0], r[1]))

        # 3. Upsert symbols
        symbols_to_upsert = []
        occurrences_to_insert = []
        superseded_treesitter_symbols = []

        from utils.helpers import demangle_scip_symbol

        for decl in declarations:
            # If a SCIP symbol exists for this declaration (via clean_symbol or occurrence coordinate), keep SCIP's symbol ID
            target_symbol_id = clean_to_existing.get(decl.clean_symbol)
            if not target_symbol_id:
                # 1. Exact line match
                target_symbol_id = line_to_existing.get(decl.start_line)
            if not target_symbol_id:
                # 2. Fuzzy line match window (+/- 2 lines) with leaf name match (e.g. for decorators/multiline signatures)
                decl_leaf = decl.name.lower().replace("_", "")
                min_delta = 999
                best_match = None
                for sym_id, s_line in occ_list:
                    delta = abs(decl.start_line - s_line)
                    if delta <= 2:
                        scip_clean = demangle_scip_symbol(sym_id)
                        scip_leaf = re.split(r"[/:\\.#]", scip_clean.rstrip("()").replace("().", ""))[-1].lower().replace("_", "")
                        if scip_leaf == decl_leaf:
                            if delta < min_delta:
                                min_delta = delta
                                best_match = sym_id
                if best_match:
                    target_symbol_id = best_match

            if not target_symbol_id:
                target_symbol_id = decl.clean_symbol

            decl.symbol = target_symbol_id

            if target_symbol_id != decl.clean_symbol and decl.clean_symbol in existing:
                superseded_treesitter_symbols.append(decl.clean_symbol)

            symbols_to_upsert.append({
                "symbol": target_symbol_id,
                "clean_symbol": decl.clean_symbol,
                "filepath": norm_fp,
                "kind": decl.kind,
                "signature": decl.signature,
                "docstring": decl.docstring,
                "body_hash": decl.body_hash,
                "parent_symbol": decl.parent_symbol,
                "code_block": decl.code_block,
            })

            # Occurrence for definition (Role = 1)
            occurrences_to_insert.append({
                "symbol": target_symbol_id,
                "filepath": norm_fp,
                "start_line": decl.start_line,
                "start_col": decl.start_col,
                "end_line": decl.end_line,
                "end_col": decl.end_col,
                "role": 1,  # SCIP SymbolRole.Definition
            })

        # Remove any superseded duplicate Tree-sitter rows
        if superseded_treesitter_symbols:
            with repository.db_conn.session() as conn:
                conn.execute(
                    "DELETE FROM symbols WHERE symbol IN (SELECT UNNEST(?::VARCHAR[]))",
                    (superseded_treesitter_symbols,)
                )

        # Upsert symbols
        repository.symbols.upsert_symbols_bulk(symbols_to_upsert)

        # Replace definition occurrences for this file
        with repository.db_conn.session() as conn:
            conn.execute(
                "DELETE FROM occurrences WHERE (replace(filepath, '\\', '/') = ? OR filepath = ?) AND role = 1",
                (norm_fp, norm_fp)
            )
        repository.symbols.add_occurrences_bulk(occurrences_to_insert)

        return declarations

    @classmethod
    def sync_project_to_db(
        cls,
        repository,
        project_root: Path,
        filepaths: Optional[Union[Set[str], List[str]]] = None,
        languages: Optional[List[str]] = None,
    ) -> int:
        """
        Scans workspace files, parses AST declarations with Tree-sitter,
        and synchronizes files, symbols, and definitions into DuckDB.
        Returns total number of symbols extracted.
        """
        from utils.exclusions import load_include_dirs, load_exclude_patterns, is_included, is_excluded
        project_root = Path(project_root)
        include_dirs = load_include_dirs(project_root)
        exclude_patterns = load_exclude_patterns(project_root)
        total_symbols = 0

        target_files = []
        if filepaths:
            for fp in filepaths:
                p = (project_root / fp) if not Path(fp).is_absolute() else Path(fp)
                if p.exists() and p.is_file():
                    target_files.append(p)
        else:
            for ext in TreesitterLoader.EXTENSION_MAP.keys():
                for p in project_root.rglob(f"*{ext}"):
                    try:
                        rel = p.relative_to(project_root)
                        rel_str = str(rel).replace("\\", "/")
                        if is_excluded(rel_str, exclude_patterns):
                            continue
                        if include_dirs and not is_included(rel_str, include_dirs, exclude_patterns):
                            continue
                        lang = TreesitterLoader.detect_language(p)
                        if languages and lang not in languages:
                            continue
                        target_files.append(p)
                    except ValueError:
                        continue

        for p in target_files:
            try:
                decls = cls.sync_file_to_db(repository, p, project_root=project_root)
                total_symbols += len(decls)
            except Exception:
                pass

        return total_symbols
