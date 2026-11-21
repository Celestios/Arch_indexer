"""Shared handler for workspace overview and compliance reports."""
from reporter.generator import Reporter


def handle_report(repository, name: str, output_format: str = "markdown") -> str:
    """Generates a workspace report in markdown or json format."""
    return Reporter(repository).generate_report(name, output_format)
