import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Optional
from db.repository import Repository


class GitCouplingMiner:
    """Mines historical git commit logs to build a pairwise file co-change coupling graph."""

    @staticmethod
    def mine_git_co_changes(project_root: Path, repository: Repository, max_commits: int = 500) -> int:
        """
        Parses git log commits to compute pairwise file co-change frequencies.
        Stores results in the file_co_changes table.
        Returns the number of pairwise co-change relations recorded.
        """
        try:
            res = subprocess.run(
                ["git", "log", "--name-only", "--format=commit:%H", f"-n{max_commits}"],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False
            )
            if res.returncode != 0 or not res.stdout:
                return 0
        except Exception:
            return 0

        lines = res.stdout.splitlines()
        commits: List[List[str]] = []
        current_commit_files: List[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("commit:"):
                if current_commit_files:
                    commits.append(current_commit_files)
                    current_commit_files = []
            else:
                norm_p = line.replace("\\", "/")
                current_commit_files.append(norm_p)

        if current_commit_files:
            commits.append(current_commit_files)

        if not commits:
            return 0

        file_commit_counts: Dict[str, int] = defaultdict(int)
        co_change_pairs: Dict[tuple[str, str], int] = defaultdict(int)

        for commit_files in commits:
            unique_files = list(set(commit_files))
            for f in unique_files:
                file_commit_counts[f] += 1
            n = len(unique_files)
            for i in range(n):
                for j in range(i + 1, n):
                    f_a = unique_files[i]
                    f_b = unique_files[j]
                    co_change_pairs[(f_a, f_b)] += 1
                    co_change_pairs[(f_b, f_a)] += 1

        records = []
        for (f_a, f_b), cnt in co_change_pairs.items():
            total_a = file_commit_counts[f_a]
            if total_a > 0:
                freq = round(cnt / total_a, 4)
                records.append((f_a, f_b, cnt, freq))

        repository.workspace.clear_co_changes()
        if records:
            repository.workspace.record_co_changes(records)

        return len(records)

    @staticmethod
    def get_co_changed_files(
        repository: Repository,
        filepath: str,
        min_frequency: float = 0.25,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieves files historically co-changed with filepath above min_frequency."""
        if not filepath:
            return []
        return repository.workspace.get_co_changes(filepath=filepath, min_frequency=min_frequency, limit=limit)
