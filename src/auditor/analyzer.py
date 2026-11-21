import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from db.repository import Repository
from auditor.classifier import SymbolClassifier
from auditor.propagation import MetadataPropagator
from auditor.field_validator import FieldValidator
from auditor.snapshot import AuditSnapshot
from auditor.violation_checkers.dependency import check as check_dependency_violations
from auditor.violation_checkers.naming import check as check_naming_violations
from auditor.violation_checkers.pending import check as check_pending_violations
from change_tracker.tracker import check_config_changed, update_config_hash
from engines.edge_weights import update_edge_weights
from utils.arch_config import ArchConfig
from utils.helpers import config_path_for, load_config


class Auditor:
    """Evaluates workspace architectural boundary compliance rules over an immutable AuditSnapshot."""

    def __init__(self, repository: Repository, project_root: Path):
        self.repository = repository
        self.project_root = project_root
        self.config_path = config_path_for(project_root)

        self.classifier = SymbolClassifier()
        self.propagator = MetadataPropagator()
        self.field_validator = FieldValidator(repository)
        self.checkers = [
            check_dependency_violations,
            check_naming_violations,
            check_pending_violations,
        ]

    def run_audit(self, filepath_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        config = load_config(self.project_root)
        if not config:
            print("No architectural rules found in .arch/config.json. Skipping audit.", file=sys.stderr)
            return []

        self._clear_old_violations(filepath_filter)
        self.field_validator.reset_invalid_manual_fields(config)
        self._handle_config_change()

        snapshot = AuditSnapshot.build(self.repository)
        symbol_classifications = self._classify_symbols(
            snapshot.all_symbols,
            snapshot.outgoing_map,
            config,
            snapshot.all_files,
        )

        propagation_sources = self.propagator.run_propagation(
            symbol_classifications, snapshot.all_edges, config
        )
        update_edge_weights(self.repository, snapshot.all_edges, symbol_classifications, config)

        classification_updates = {sym: data["fields"] for sym, data in symbol_classifications.items()}
        self.repository.graph.update_symbols_classification(classification_updates)

        violations = []
        for checker in self.checkers:
            violations.extend(checker(
                snapshot=snapshot,
                symbol_classifications=symbol_classifications,
                propagation_sources=propagation_sources,
                config=config,
                filepath_filter=filepath_filter,
            ))

        self.repository.quality.upsert_violations(violations)
        self._recompute_file_statuses(violations, snapshot.all_files, filepath_filter)
        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.", file=sys.stderr)
        return violations

    def _clear_old_violations(self, filepath_filter: Optional[str]):
        if filepath_filter:
            self.repository.quality.delete_violations(filepath_prefix=filepath_filter, origin="automatic")
        else:
            self.repository.quality.delete_violations(origin="automatic")

    def _handle_config_change(self):
        if check_config_changed(self.project_root, self.repository):
            update_config_hash(self.project_root, self.repository)

    def _classify_symbols(
        self,
        all_symbols: List[Dict[str, Any]],
        outgoing_map: Dict[str, List[str]],
        config: ArchConfig,
        file_metadata: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        symbol_to_filepath = {s["symbol"]: s.get("filepath") for s in all_symbols if "symbol" in s}
        symbol_classifications = {}
        for sym in all_symbols:
            filepath = sym.get("filepath")
            if not filepath:
                continue
            prefix_conf = config.get_applicable_config(filepath)
            if not prefix_conf:
                continue
            outgoing = outgoing_map.get(sym["symbol"], [])
            classifications = self.classifier.assign_automatic_fields(
                sym, prefix_conf, outgoing, symbol_to_filepath=symbol_to_filepath
            )
            if filepath in file_metadata:
                manual_fields = file_metadata[filepath].get("manual_fields") or {}
                classifications.update(manual_fields)
            symbol_classifications[sym["symbol"]] = {
                "symbol_info": sym,
                "fields": classifications,
                "static_fields": dict(classifications),
                "prefix_conf": prefix_conf,
            }
        return symbol_classifications

    def _recompute_file_statuses(
        self,
        violations: List[Dict[str, Any]],
        file_metadata: Dict[str, Dict[str, Any]],
        filepath_filter: Optional[str] = None,
    ):
        violations_by_file: Dict[str, List[str]] = {}
        for v in violations:
            violations_by_file.setdefault(v["filepath"], []).append(v.get("origin", "automatic"))

        if filepath_filter:
            files_to_update = set(violations_by_file.keys())
            for f_path in file_metadata.keys():
                if f_path.startswith(filepath_filter):
                    files_to_update.add(f_path)
        else:
            files_to_update = set(file_metadata.keys())

        statuses_to_update = {
            f_path: (
                "COMPLIANT"
                if not violations_by_file.get(f_path) or all(o != "automatic" for o in violations_by_file[f_path])
                else "VIOLATION_DETECTED"
            )
            for f_path in files_to_update
        }
        self.repository.workspace.update_file_statuses(statuses_to_update)
