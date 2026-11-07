import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

from db.repository import Repository
from auditor.classifier import SymbolClassifier
from auditor.propagation import MetadataPropagator
from auditor.path_tracer import PathTracer
from auditor.config_loader import ConfigLoader
from auditor.field_validator import FieldValidator
from auditor.edge_weights import EdgeWeightUpdater
from auditor.registry import ViolationCheckerRegistry
from auditor.violation_checkers.dependency import DependencyViolationChecker
from auditor.violation_checkers.naming import NamingViolationChecker
from auditor.violation_checkers.pending import PendingAuditChecker
from utils.helpers import config_path_for, load_config


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

        self.config_loader = ConfigLoader(self.config_path)
        self.classifier = SymbolClassifier(repository)
        self.propagator = MetadataPropagator()
        self.tracer = PathTracer(repository)
        self.field_validator = FieldValidator(repository, self.config_loader)
        self.edge_weight_updater = EdgeWeightUpdater(repository)

        self.dependency_checker = DependencyViolationChecker(repository, self.tracer, self.config_loader)
        self.naming_checker = NamingViolationChecker(repository, self.tracer)
        self.pending_checker = PendingAuditChecker()

        ViolationCheckerRegistry.clear()
        ViolationCheckerRegistry.register(self.dependency_checker)
        ViolationCheckerRegistry.register(self.naming_checker)
        ViolationCheckerRegistry.register(self.pending_checker)

    def load_config(self) -> Dict[str, Any]:
        """Loads the workspace architectural configuration."""
        return load_config(self.project_root)

    def run_audit(self, filepath_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Runs the architectural compliance audit.
        Resolves symbols classifications, checks dependency rules, and saves violations.
        If filepath_filter is provided, only audits files matching that path prefix.
        """
        config = self.config_loader.load_config()
        if not config:
            print("No architectural rules found in .arch/config.json. Skipping audit.")
            return []

        self._clear_old_violations(filepath_filter)
        self.field_validator.reset_invalid_manual_fields(config)
        self._handle_config_change()

        all_symbols = self._fetch_all_symbols()
        outgoing_map = self._build_outgoing_map(all_symbols)
        symbol_classifications = self._classify_symbols(all_symbols, outgoing_map, config)
        all_edges = self._fetch_all_edges()

        propagation_sources = self.propagator.run_propagation(symbol_classifications, all_edges, config)
        self.edge_weight_updater.update_edge_weights(all_edges, symbol_classifications, config)

        violations = []
        for checker in ViolationCheckerRegistry.get_all():
            violations.extend(checker.check(
                self.repository, symbol_classifications, all_edges,
                config, filepath_filter, propagation_sources
            ))

        self._recompute_file_statuses(violations, filepath_filter)
        print(f"[Auditor] Completed audit. Found {len(violations)} architectural violations.")
        return violations

    def _clear_old_violations(self, filepath_filter: Optional[str]):
        if filepath_filter:
            self.repository.compliance.delete_automatic_violations_for_path(filepath_filter)
        else:
            self.repository.compliance.delete_automatic_violations()

    def _handle_config_change(self):
        from change_tracker.tracker import ChangeTracker
        config_changed = ChangeTracker.check_config_changed(self.project_root, self.repository)
        if config_changed:
            ChangeTracker.update_config_hash(self.project_root, self.repository)

    def _fetch_all_symbols(self) -> List[Dict[str, Any]]:
        return self.repository.symbols.get_all_symbols_with_metadata()

    def _build_outgoing_map(self, all_symbols: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        outgoing_calls_map = {}
        for sym in all_symbols:
            outgoing = self.repository.edges.get_outgoing_edges(sym["symbol"])
            outgoing_calls_map[sym["symbol"]] = [o["target"] for o in outgoing]
        return outgoing_calls_map

    def _classify_symbols(self, all_symbols, outgoing_map, config) -> Dict[str, Dict[str, Any]]:
        file_metadata = self.repository.files.get_all_files_metadata()
        symbol_classifications = {}
        for sym in all_symbols:
            filepath = sym.get("filepath")
            if not filepath:
                continue
            prefix_conf = self.config_loader.get_applicable_config(filepath, config)
            if not prefix_conf:
                continue
            outgoing = outgoing_map.get(sym["symbol"], [])
            classifications = self.classifier.assign_automatic_fields(sym, prefix_conf, outgoing)
            if filepath in file_metadata:
                manual_fields = file_metadata[filepath].get("manual_fields") or {}
                classifications.update(manual_fields)
            symbol_classifications[sym["symbol"]] = {
                "symbol_info": sym, "fields": classifications,
                "static_fields": dict(classifications), "prefix_conf": prefix_conf
            }
        return symbol_classifications

    def _fetch_all_edges(self) -> List[Dict[str, Any]]:
        return self.repository.edges.get_all_edges_with_relation()

    def _recompute_file_statuses(self, violations, filepath_filter: Optional[str] = None):
        violations_by_file = {}
        for v in violations:
            violations_by_file.setdefault(v["filepath"], []).append(v.get("origin", "automatic"))

        if filepath_filter:
            files_to_update = set()
            for f_path in violations_by_file.keys():
                files_to_update.add(f_path)
            file_metadata = self.repository.files.get_all_files_metadata()
            for f_path in file_metadata.keys():
                if f_path.startswith(filepath_filter):
                    files_to_update.add(f_path)
        else:
            files_to_update = set(self.repository.files.get_all_files_metadata().keys())

        for f_path in files_to_update:
            v_origins = violations_by_file.get(f_path, [])
            new_status = "COMPLIANT" if not v_origins or all(o != "automatic" for o in v_origins) else "VIOLATION_DETECTED"
            self.repository.files.update_file_status(f_path, new_status)
