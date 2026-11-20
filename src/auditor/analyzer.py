import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from db.repository import Repository
from auditor.classifier import SymbolClassifier
from auditor.propagation import MetadataPropagator
from auditor.path_tracer import PathTracer
from auditor.field_validator import FieldValidator
from engines.edge_weights import EdgeWeightUpdater
from auditor.snapshot import AuditSnapshot
from auditor.violation_checkers.dependency import DependencyViolationChecker
from auditor.violation_checkers.naming import NamingViolationChecker
from auditor.violation_checkers.pending import PendingAuditChecker
from utils.helpers import config_path_for, load_config
from utils.arch_config import ArchConfig


class Auditor:
    """
    Evaluates workspace architectural boundary compliance rules.
    Loads configurations from .arch/config.json and audits symbols/edges inside the database.
    Delegates tasks to classifier, propagator, and path tracer modules.
    """

    def __init__(self, repository: Repository, project_root: Path):
        self.repository = repository
        self.project_root = project_root
        self.config_path = config_path_for(project_root)

        self.config_loader = None
        self.classifier = SymbolClassifier(repository)
        self.propagator = MetadataPropagator()
        self.tracer = PathTracer(repository)
        self.field_validator = FieldValidator(repository, self.config_loader)
        self.edge_weight_updater = EdgeWeightUpdater(repository)

        self.checkers = [
            DependencyViolationChecker(repository, self.tracer, self.config_loader),
            NamingViolationChecker(repository, self.tracer),
            PendingAuditChecker(repository),
        ]

    def load_config(self) -> Dict[str, Any]:
        """Loads the workspace architectural configuration."""
        return load_config(self.project_root)

    def run_audit(self, filepath_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Runs the architectural compliance audit.
        Resolves symbols classifications, checks dependency rules, and saves violations.
        If filepath_filter is provided, only audits files matching that path prefix.
        """
        config = self.config_loader.load_config() if self.config_loader else self.load_config()
        if not config:
            print("No architectural rules found in .arch/config.json. Skipping audit.", file=sys.stderr)
            return []

        self._clear_old_violations(filepath_filter)
        self.field_validator.reset_invalid_manual_fields(config)
        self._handle_config_change()

        snapshot = AuditSnapshot.build(self.repository)
        all_symbols = snapshot.all_symbols
        all_edges = snapshot.all_edges
        outgoing_map = snapshot.outgoing_map
        symbol_classifications = self._classify_symbols(all_symbols, outgoing_map, config, file_metadata=snapshot.all_files)

        propagation_sources = self.propagator.run_propagation(symbol_classifications, all_edges, config)
        self.edge_weight_updater.update_edge_weights(all_edges, symbol_classifications, config)

        # Persist resolved classification metadata onto symbols table for context badges
        classification_updates = {sym: data["fields"] for sym, data in symbol_classifications.items()}
        self.repository.graph.update_symbols_classification_bulk(classification_updates)

        violations = []
        for checker in self.checkers:
            violations.extend(checker.check(
                snapshot=snapshot,
                symbol_classifications=symbol_classifications,
                config=config,
                filepath_filter=filepath_filter,
                propagation_sources=propagation_sources,
            ))

        self.repository.quality.record_violations_bulk(violations)
        self._recompute_file_statuses(violations, filepath_filter, file_metadata=snapshot.all_files)
        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.", file=sys.stderr)
        return violations

    def _clear_old_violations(self, filepath_filter: Optional[str]):
        if filepath_filter:
            self.repository.quality.delete_automatic_violations_for_path(filepath_filter)
        else:
            self.repository.quality.delete_automatic_violations()

    def _handle_config_change(self):
        from change_tracker.tracker import ChangeTracker
        config_changed = ChangeTracker.check_config_changed(self.project_root, self.repository)
        if config_changed:
            ChangeTracker.update_config_hash(self.project_root, self.repository)

    def _classify_symbols(self, all_symbols, outgoing_map, config, file_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        if file_metadata is None:
            file_metadata = self.repository.workspace.get_all_files_metadata()
        symbol_to_filepath = {s["symbol"]: s.get("filepath") for s in all_symbols if "symbol" in s}
        symbol_classifications = {}
        for sym in all_symbols:
            filepath = sym.get("filepath")
            if not filepath:
                continue
            if self.config_loader and hasattr(self.config_loader, "get_applicable_config"):
                prefix_conf = self.config_loader.get_applicable_config(filepath, config)
            elif hasattr(config, "get_applicable_config"):
                prefix_conf = config.get_applicable_config(filepath)
            else:
                prefix_conf = ArchConfig.find_applicable_config(filepath, config)
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
                "symbol_info": sym, "fields": classifications,
                "static_fields": dict(classifications), "prefix_conf": prefix_conf
            }
        return symbol_classifications

    def _recompute_file_statuses(self, violations, filepath_filter: Optional[str] = None, file_metadata: Optional[Dict[str, Any]] = None):
        violations_by_file = {}
        for v in violations:
            violations_by_file.setdefault(v["filepath"], []).append(v.get("origin", "automatic"))

        if file_metadata is None:
            file_metadata = self.repository.workspace.get_all_files_metadata()

        if filepath_filter:
            files_to_update = set()
            for f_path in violations_by_file.keys():
                files_to_update.add(f_path)
            for f_path in file_metadata.keys():
                if f_path.startswith(filepath_filter):
                    files_to_update.add(f_path)
        else:
            files_to_update = set(file_metadata.keys())

        statuses_to_update = {}
        for f_path in files_to_update:
            v_origins = violations_by_file.get(f_path, [])
            new_status = "COMPLIANT" if not v_origins or all(o != "automatic" for o in v_origins) else "VIOLATION_DETECTED"
            statuses_to_update[f_path] = new_status
        self.repository.workspace.update_file_statuses(statuses_to_update)
