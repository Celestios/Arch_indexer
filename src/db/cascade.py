"""Cross-table cascade delete coordination."""
from typing import List


class CascadeCleanupService:
    """Coordinates cross-table deletes for file removal."""

    def __init__(self, repository):
        self.repository = repository

    def delete_file(self, filepath: str):
        """Delete a file and all its associated data across tables."""
        if hasattr(self.repository, "graph") and hasattr(self.repository.graph, "delete_files"):
            self.repository.graph.delete_files([filepath])
        else:
            self.repository.edges.delete_edges_for_file(filepath)
            self.repository.occurrences.delete_occurrences_for_file(filepath)
            self.repository.diagnostics.delete_diagnostics_for_file(filepath)
            self.repository.symbols.delete_symbols_for_file(filepath)
            self.repository.files.delete_file_record(filepath)

    def delete_files_bulk(self, filepaths: List[str]):
        """Delete multiple files and all associated data."""
        if not filepaths:
            return
        if hasattr(self.repository, "graph") and hasattr(self.repository.graph, "delete_files"):
            self.repository.graph.delete_files(filepaths)
        else:
            self.repository.edges.delete_edges_for_files(filepaths)
            self.repository.occurrences.delete_occurrences_for_files(filepaths)
            self.repository.diagnostics.delete_diagnostics_for_files(filepaths)
            self.repository.symbols.delete_symbols_for_files(filepaths)
            self.repository.files.delete_files_records(filepaths)
