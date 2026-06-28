import json
from typing import Dict, List, Any, Type, Optional
from db.repository import Repository

class BaseReport:
    """
    Abstract base class for all workspace reports.
    """
    def __init__(self, repository: Repository):
        self.repository = repository

    def generate(self) -> Dict[str, Any]:
        """
        Executes database queries and returns structured data as a dictionary.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Reports must implement the generate method.")

    def to_markdown(self, data: Dict[str, Any]) -> str:
        """
        Formats the generated report data into a Markdown string.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Reports must implement the to_markdown method.")

    def to_json(self, data: Dict[str, Any]) -> str:
        """
        Formats the generated report data into a JSON string.
        """
        return json.dumps(data, indent=2, default=str)


class OverviewReport(BaseReport):
    """
    Generates a high-level summary of the codebase statistics.
    """
    def generate(self) -> Dict[str, Any]:
        totals = self.repository.get_repo_totals()
        kinds = self.repository.get_symbol_counts_by_kind()
        prefixes = self.repository.get_symbols_by_file_prefix()
        return {
            "totals": totals,
            "kinds": kinds,
            "prefixes": prefixes
        }

    def to_markdown(self, data: Dict[str, Any]) -> str:
        totals = data.get("totals", {})
        kinds = data.get("kinds", {})
        prefixes = data.get("prefixes", {})

        md = ["# Workspace Overview Report\n"]
        md.append("## Repository Totals")
        md.append(f"- **Files Indexed**: {totals.get('files', 0)}")
        md.append(f"- **Symbols Registered**: {totals.get('symbols', 0)}")
        md.append(f"- **Dependencies (Call Graph Edges)**: {totals.get('edges', 0)}")
        md.append(f"- **Active Architectural Violations**: {totals.get('violations', 0)}")
        md.append("")

        md.append("## Symbol Types Breakdown")
        if not kinds:
            md.append("*No symbol types found.*")
        else:
            for k, count in sorted(kinds.items()):
                md.append(f"- **{k.capitalize()}**: {count}")
        md.append("")

        md.append("## Subdirectory File Distributions")
        if not prefixes:
            md.append("*No subdirectories mapped.*")
        else:
            for prefix, count in sorted(prefixes.items(), key=lambda x: x[1], reverse=True):
                md.append(f"- `{prefix}`: {count} symbol(s)")
        md.append("")

        return "\n".join(md)


class ComplianceReport(BaseReport):
    """
    Generates a detailed summary of all active architectural compliance violations.
    """
    def generate(self) -> Dict[str, Any]:
        violations = self.repository.get_violations()
        summary = {"warning": 0, "critical": 0, "info": 0}
        for v in violations:
            sev = v.get("severity", "warning").lower()
            summary[sev] = summary.get(sev, 0) + 1
        return {
            "summary": summary,
            "violations": violations
        }

    def to_markdown(self, data: Dict[str, Any]) -> str:
        summary = data.get("summary", {})
        violations = data.get("violations", [])

        md = ["# Compliance Violations Report\n"]
        md.append("## Severity Summary")
        md.append(f"- **Critical Errors**: {summary.get('critical', 0)}")
        md.append(f"- **Warnings**: {summary.get('warning', 0)}")
        md.append(f"- **Info Boundary Checks**: {summary.get('info', 0)}")
        md.append("")

        md.append("## Active Violations List")
        if not violations:
            md.append("*No compliance violations found in the catalog.*")
        else:
            for i, v in enumerate(violations, 1):
                md.append(f"{i}. **[{v['rule_id']}]** (Severity: `{v['severity']}`)")
                md.append(f"   - **File**: `{v['filepath']}:L{v['line']}`")
                md.append(f"   - **Symbol**: `{v['symbol']}`")
                md.append(f"   - **Violation Description**: {v['message']}")
                md.append(f"   - **Rule Details**: {v.get('rule_description', 'No description available')}")
                md.append("")
        return "\n".join(md)


class Reporter:
    """
    Manages and generates workspace reports.
    """
    def __init__(self, repository: Repository):
        self.repository = repository
        self._registry: Dict[str, Type[BaseReport]] = {
            "overview": OverviewReport,
            "compliance": ComplianceReport
        }

    def register_report(self, name: str, report_class: Type[BaseReport]):
        """Registers a new report type in the framework."""
        self._registry[name] = report_class

    def list_reports(self) -> List[str]:
        """Returns the keys of all registered reports."""
        return sorted(list(self._registry.keys()))

    def generate_report(self, name: str, output_format: str = "markdown") -> str:
        """
        Executes the named report and returns it formatted in the specified format (json/markdown).
        """
        if name not in self._registry:
            raise KeyError(f"Report '{name}' is not registered. Choose from: {', '.join(self.list_reports())}")

        report_inst = self._registry[name](self.repository)
        data = report_inst.generate()

        if output_format.lower() == "json":
            return report_inst.to_json(data)
        else:
            return report_inst.to_markdown(data)
