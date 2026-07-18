from reporter.generator import Reporter


def handle_report(name: str, format: str, repository) -> str:
    """Generate a structured workspace report. Returns markdown or json string."""
    reporter = Reporter(repository)
    return reporter.generate_report(name, format)
