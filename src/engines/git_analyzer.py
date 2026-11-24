"""
Centralized on-the-fly Git evolution, hotspot, thrash, temporal coupling,
growth, test-gap, and symbol archaeology engine.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from utils.exclusions import (
    is_boilerplate,
    is_excluded,
    is_included,
    load_exclude_patterns,
    load_include_dirs,
)
from utils.helpers import (
    is_auxiliary_path,
    is_test_caller,
    load_config,
    normalize_scopes,
)
from utils.symbol_id import canonical_display_name

logger = logging.getLogger(__name__)

NON_CODE_EXTENSIONS: Set[str] = {
    ".lock", ".md", ".txt", ".rst", ".surql", ".toml", ".yaml", ".yml", ".json",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".env", ".csv",
    ".scip", ".db", ".wal", ".pdf", ".zip", ".tar", ".gz", ".exe", ".dll",
    ".so", ".dylib", ".wasm", ".ttf", ".otf", ".woff", ".woff2", ".map",
}

HALF_LIFE_COMMITS = 20.0
DECAY_LAMBDA = math.log(2.0) / HALF_LIFE_COMMITS

_COMMIT_MARKER = "__ARCH_COMMIT__"
_ARCH_MARKER = "__ARCH_ARCH__"
_FIELD_SEP = "\x1f"

_FIX_RE = re.compile(r"\b(fix|fixed|fixes|bug|bugfix|issue|patch|hotfix|regression)\b", re.IGNORECASE)
_REVERT_RE = re.compile(r"\b(revert|reverted|rollback|undo)\b", re.IGNORECASE)
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_RENAME_BRACE_RE = re.compile(r"(.*)\{([^{}]*) => ([^{}]*)\}(.*)")


@dataclass(frozen=True)
class CommitRecord:
    """Normalized representation of a single non-merge Git commit."""
    commit_hash: str
    index: int
    timestamp: int
    subject: str
    is_revert: bool
    is_fix_msg: bool
    files: Dict[str, Tuple[int, int]] = field(default_factory=dict)


@dataclass
class _GraphContext:
    """Single-pass structural snapshot extracted from DuckDB for Git enrichment."""
    file_fan_in: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    file_fan_out: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    file_max_conn: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    file_symbol_count: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    static_file_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    file_test_callers: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    symbol_to_fp: Dict[str, str] = field(default_factory=dict)


def _norm_posix(path_str: Optional[str]) -> str:
    if not path_str:
        return ""
    norm = path_str.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.strip("/")


def _clean_numstat_path(raw_path: str) -> str:
    """Resolves git rename notation to the destination POSIX path."""
    path = raw_path.strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    m = _RENAME_BRACE_RE.match(path)
    if m:
        prefix, _, new_part, suffix = m.groups()
        resolved = f"{prefix}{new_part}{suffix}".replace("//", "/")
        return _norm_posix(resolved)
    if " => " in path:
        return _norm_posix(path.split(" => ", 1)[1])
    return _norm_posix(path)


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5,
                check=False,
            )
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def _run_git(args: List[str], project_root: Path, timeout: int = 20) -> Optional[str]:
    """Executes a git command safely under MCP stdio/daemon constraints without pipe deadlocks."""
    cmd = [
        "git",
        "--no-pager",
        "-c", "core.fsmonitor=false",
        "-c", "gc.auto=0",
        "-c", "core.quotepath=false",
    ] + args
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_PAGER": "cat",
    }
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            if stderr and stderr.strip():
                logger.warning("git %s failed: %s", " ".join(args[:3]), stderr.strip())
            return None
        return stdout
    except subprocess.TimeoutExpired:
        if proc is not None:
            _kill_process_tree(proc)
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except Exception:
                        pass
        logger.warning("git %s timed out after %ds", " ".join(args[:3]), timeout)
        return None
    except (FileNotFoundError, OSError) as e:
        logger.warning("git execution error: %s", e)
        return None


def is_git_repo(project_root: Path) -> bool:
    if (project_root / ".git").exists():
        return True
    out = _run_git(["rev-parse", "--is-inside-work-tree"], project_root, timeout=5)
    return bool(out and out.strip().lower() == "true")


def _matches_scope(norm_path: str, scope_prefixes: Optional[List[str]]) -> bool:
    if not scope_prefixes:
        return True
    return any(norm_path == s or norm_path.startswith(s + "/") for s in scope_prefixes)


def _is_test_or_aux_path(norm_path: str) -> bool:
    return is_auxiliary_path(norm_path) or is_test_caller("", norm_path)


def _is_auditable_source(
    norm_path: str,
    project_root: Path,
    include_dirs: Optional[Set[str]],
    exclude_patterns: List[str],
    scope_prefixes: Optional[List[str]] = None,
    require_exists: bool = True,
) -> bool:
    if not norm_path:
        return False
    suffix = Path(norm_path).suffix.lower()
    if suffix in NON_CODE_EXTENSIONS:
        return False
    if is_excluded(norm_path, exclude_patterns):
        return False
    if is_boilerplate(norm_path):
        return False
    if _is_test_or_aux_path(norm_path):
        return False
    if scope_prefixes is not None:
        if not _matches_scope(norm_path, scope_prefixes):
            return False
    elif include_dirs and not is_included(norm_path, include_dirs, exclude_patterns):
        return False
    if require_exists and not (project_root / norm_path).is_file():
        return False
    return True


def parse_git_history(project_root: Path, commits: int = 100) -> List[CommitRecord]:
    if commits <= 0 or not is_git_repo(project_root):
        return []

    fmt = f"{_COMMIT_MARKER}%H%x1f%ct%x1f%s"
    raw = _run_git(
        ["log", f"-n{int(commits)}", "--no-merges", "--numstat", f"--format={fmt}"],
        project_root,
    )
    if not raw:
        return []

    records: List[CommitRecord] = []
    commit_idx = 0

    for block in raw.split(_COMMIT_MARKER):
        if not block.strip():
            continue
        lines = block.splitlines()
        parts = lines[0].split(_FIELD_SEP, 2)
        if len(parts) < 3:
            continue
        commit_hash = parts[0].strip()
        try:
            timestamp = int(parts[1].strip())
        except ValueError:
            timestamp = 0
        subject = parts[2].strip()

        files_map: Dict[str, Tuple[int, int]] = {}
        for line in lines[1:]:
            if not line.strip() or "\t" not in line:
                continue
            cols = line.split("\t", 2)
            if len(cols) < 3:
                continue
            add_s, del_s, raw_fp = cols[0].strip(), cols[1].strip(), cols[2].strip()
            fp = _clean_numstat_path(raw_fp)
            if not fp:
                continue
            if add_s == "-" or del_s == "-":
                added, deleted = 0, 0
            else:
                try:
                    added, deleted = int(add_s), int(del_s)
                except ValueError:
                    added, deleted = 0, 0
            prev_a, prev_d = files_map.get(fp, (0, 0))
            files_map[fp] = (prev_a + added, prev_d + deleted)

        records.append(
            CommitRecord(
                commit_hash=commit_hash,
                index=commit_idx,
                timestamp=timestamp,
                subject=subject,
                is_revert=bool(_REVERT_RE.search(subject)),
                is_fix_msg=bool(_FIX_RE.search(subject)),
                files=files_map,
            )
        )
        commit_idx += 1

    return records


def _build_graph_context(repository) -> _GraphContext:
    ctx = _GraphContext()
    if repository is None:
        return ctx

    try:
        sym_rows = repository.graph.get_all_symbols()
        edge_rows = repository.graph.get_edges()
    except Exception:
        logger.debug("Failed to load graph snapshot for git enrichment", exc_info=True)
        return ctx

    for s in sym_rows:
        sid = s.get("symbol")
        fp = _norm_posix(s.get("filepath"))
        if not sid or not fp:
            continue
        ctx.symbol_to_fp[sid] = fp
        if not sid.startswith("local ") and s.get("kind") != "Parameter":
            ctx.file_symbol_count[fp] += 1
            conn_w = int(s.get("connection_weight") or 0)
            if conn_w > ctx.file_max_conn[fp]:
                ctx.file_max_conn[fp] = conn_w

    seen_test_callers: Dict[str, Set[str]] = defaultdict(set)
    for e in edge_rows:
        src = e.get("source")
        tgt = e.get("target")
        if not src or not tgt:
            continue
        sfp = ctx.symbol_to_fp.get(src)
        tfp = ctx.symbol_to_fp.get(tgt)
        if not sfp or not tfp or sfp == tfp:
            continue
        ctx.file_fan_out[sfp] += 1
        ctx.file_fan_in[tfp] += 1
        pair = (sfp, tfp) if sfp < tfp else (tfp, sfp)
        ctx.static_file_pairs.add(pair)

        if is_test_caller(src, sfp):
            seen_test_callers[tfp].add(src)

    for fp, callers in seen_test_callers.items():
        ctx.file_test_callers[fp] = len(callers)

    return ctx


def _count_non_empty_loc(abs_path: Path) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _compute_file_ast_metrics(abs_path: Path, project_root: Path) -> Tuple[int, int, float]:
    loc = _count_non_empty_loc(abs_path)
    if loc == 0:
        return 0, 1, 1.0
    try:
        from engines.treesitter.extractor import extract_symbols_from_file
        decls = extract_symbols_from_file(abs_path, project_root=project_root)
        complexities = [max(1, int(d.complexity)) for d in decls if d.complexity is not None]
        if complexities:
            return loc, max(complexities), round(sum(complexities) / len(complexities), 1)
    except Exception:
        pass
    return loc, 1, 1.0


def _resolve_domain_label(norm_path: str, arch_config: Any) -> str:
    if arch_config:
        prefix = arch_config.get_applicable_prefix(norm_path)
        if prefix and prefix != ".":
            return prefix.rstrip("/") + "/"
    parts = norm_path.split("/")
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}/"
    if len(parts) == 2:
        return f"{parts[0]}/"
    return "./"


def compute_file_evolution_metrics(
    commits_data: List[CommitRecord],
    project_root: Path,
    include_dirs: Optional[Set[str]],
    exclude_patterns: List[str],
    scope_prefixes: Optional[List[str]] = None,
    require_exists: bool = True,
) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}

    for commit in commits_data:
        decay = math.exp(-DECAY_LAMBDA * commit.index)
        has_test_file = any(_is_test_or_aux_path(fp) for fp in commit.files.keys())

        for fp, (added, deleted) in commit.files.items():
            if not _is_auditable_source(
                fp,
                project_root,
                include_dirs,
                exclude_patterns,
                scope_prefixes=scope_prefixes,
                require_exists=require_exists,
            ):
                continue

            entry = stats.get(fp)
            if entry is None:
                entry = {
                    "filepath": fp,
                    "touches": 0,
                    "decayed_churn": 0.0,
                    "added": 0,
                    "deleted": 0,
                    "reverts": 0,
                    "fix_touches": 0,
                    "co_modified_tests": 0,
                    "commit_indices": [],
                    "last_touched_idx": commit.index,
                }
                stats[fp] = entry

            magnitude = math.log1p(added + deleted) if (added + deleted) > 0 else 0.5
            entry["touches"] += 1
            entry["decayed_churn"] += decay * magnitude
            entry["added"] += added
            entry["deleted"] += deleted
            if commit.is_revert:
                entry["reverts"] += 1
            if commit.is_fix_msg:
                entry["fix_touches"] += 1
            if has_test_file:
                entry["co_modified_tests"] += 1
            entry["commit_indices"].append(commit.index)
            if commit.index < entry["last_touched_idx"]:
                entry["last_touched_idx"] = commit.index

    for entry in stats.values():
        indices = sorted(entry["commit_indices"])
        bursts = 0
        burst_score = 0.0
        for i in range(len(indices) - 1):
            gap = indices[i + 1] - indices[i]
            if gap <= 3:
                bursts += 1
                burst_score += math.exp(-DECAY_LAMBDA * indices[i]) * (1.0 / max(1, gap))

        added = entry["added"]
        deleted = entry["deleted"]
        total_lines = added + deleted
        churn_balance = (2.0 * min(added, deleted) / total_lines) if total_lines > 0 else 0.0
        rework_ratio = deleted / max(added, 1)
        thrash_score = (burst_score * 2.0) + (churn_balance * entry["decayed_churn"] * 0.6) + (entry["reverts"] * 3.0)

        entry["net_growth"] = added - deleted
        entry["churn_balance"] = round(churn_balance, 3)
        entry["rework_pct"] = int(round(churn_balance * 100))
        entry["rework_ratio"] = round(rework_ratio, 2)
        entry["bursts"] = bursts
        entry["burst_score"] = round(burst_score, 3)
        entry["decayed_churn"] = round(entry["decayed_churn"], 2)
        entry["thrash_score"] = round(thrash_score, 2)

    return stats


def _assign_risk_tier(risk_score: float, max_score: float) -> str:
    if risk_score >= 45.0 or (max_score >= 20.0 and risk_score >= max_score * 0.80):
        return "CRITICAL"
    if risk_score >= 22.0 or (max_score >= 12.0 and risk_score >= max_score * 0.50):
        return "HIGH"
    if risk_score >= 8.0:
        return "ELEVATED"
    return "LOW"


def _analyze_file_symbol_hotspots(
    repository,
    project_root: Path,
    filepath: str,
    commits: int = 100,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    if repository is None:
        return []
    syms = repository.graph.get_symbols_for_files([filepath])
    callable_syms = [
        s for s in syms
        if s.get("start_line") is not None
        and not str(s.get("symbol", "")).startswith("local ")
        and str(s.get("kind", "")).lower() not in ("module", "package", "parameter")
    ]
    if not callable_syms:
        return []

    callable_syms.sort(
        key=lambda s: ((s.get("end_line") or s["start_line"]) - s["start_line"], s["start_line"])
    )

    fmt = f"{_COMMIT_MARKER}%H%x1f%ct%x1f%s"
    raw = _run_git(
        ["log", f"-n{int(commits)}", "--no-merges", "-U0", f"--format={fmt}", "--", filepath],
        project_root,
    )
    if not raw:
        return []

    sym_touches: Dict[str, Dict[str, Any]] = {}
    commit_idx = 0

    for block in raw.split(_COMMIT_MARKER):
        if not block.strip():
            continue
        lines = block.splitlines()
        header_parts = lines[0].split(_FIELD_SEP, 2)
        if len(header_parts) < 3:
            continue
        subject = header_parts[2].strip()
        is_revert = bool(_REVERT_RE.search(subject))
        decay = math.exp(-DECAY_LAMBDA * commit_idx)

        touched_in_commit: Dict[str, int] = defaultdict(int)
        for line in lines[1:]:
            m = _HUNK_RE.match(line)
            if not m:
                continue
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            new_end = new_start + max(new_count - 1, 0)
            span_lines = max(new_count, int(m.group(2)) if m.group(2) is not None else 1, 1)

            for s in callable_syms:
                s_start = int(s["start_line"])
                s_end = int(s.get("end_line") or s_start)
                if s_start <= new_end and new_start <= s_end:
                    touched_in_commit[s["symbol"]] += span_lines
                    break

        for sid, delta_lines in touched_in_commit.items():
            rec = sym_touches.setdefault(
                sid,
                {"touches": 0, "decayed_churn": 0.0, "reverts": 0, "commit_indices": []},
            )
            rec["touches"] += 1
            rec["decayed_churn"] += decay * math.log1p(delta_lines)
            if is_revert:
                rec["reverts"] += 1
            rec["commit_indices"].append(commit_idx)

        commit_idx += 1

    sym_lookup = {s["symbol"]: s for s in callable_syms}
    results: List[Dict[str, Any]] = []
    for sid, rec in sym_touches.items():
        s = sym_lookup[sid]
        indices = sorted(rec["commit_indices"])
        bursts = sum(1 for i in range(len(indices) - 1) if indices[i + 1] - indices[i] <= 3)
        conn_w = int(s.get("connection_weight") or 0)
        risk = round(
            (rec["decayed_churn"] * 1.5 + bursts * 1.5 + rec["reverts"] * 3.0) * (1.0 + math.log1p(conn_w)),
            1,
        )
        results.append({
            "symbol": canonical_display_name(sid, s.get("name")),
            "raw_symbol": sid,
            "kind": s.get("kind") or "Symbol",
            "filepath": filepath,
            "start_line": int(s["start_line"]),
            "end_line": int(s.get("end_line") or s["start_line"]),
            "touches": rec["touches"],
            "bursts": bursts,
            "reverts": rec["reverts"],
            "connection_weight": conn_w,
            "risk_score": risk,
        })

    results.sort(key=lambda x: (-x["risk_score"], -x["touches"], x["start_line"]))
    return results[:limit]


def analyze_hotspots(
    commits_data: List[CommitRecord],
    repository,
    project_root: Path,
    scope: Optional[Union[str, List[str]]] = None,
    target: Optional[str] = None,
    commits: int = 100,
    limit: int = 10,
    graph_ctx: Optional[_GraphContext] = None,
    file_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
    require_exists: bool = True,
) -> Dict[str, Any]:
    include_dirs = load_include_dirs(project_root)
    exclude_patterns = load_exclude_patterns(project_root)
    scope_prefixes = normalize_scopes(scope)
    gctx = graph_ctx if graph_ctx is not None else _build_graph_context(repository)
    arch_config = load_config(project_root)

    if file_metrics is None:
        file_metrics = compute_file_evolution_metrics(
            commits_data,
            project_root,
            include_dirs,
            exclude_patterns,
            scope_prefixes=scope_prefixes,
            require_exists=require_exists,
        )

    prelim: List[Tuple[float, str, Dict[str, Any]]] = []
    for fp, m in file_metrics.items():
        if target and fp != target:
            continue
        fan_in = gctx.file_fan_in.get(fp, 0)
        rough = (m["decayed_churn"] * 1.5 + m["thrash_score"] * 1.2 + m["fix_touches"] * 0.8) * (
            1.0 + math.log1p(fan_in)
        )
        prelim.append((rough, fp, m))

    prelim.sort(key=lambda x: x[0], reverse=True)
    eval_cap = max(limit * 3, 25)

    scored: List[Dict[str, Any]] = []
    for _, fp, m in prelim[:eval_cap]:
        abs_p = project_root / fp
        loc, max_cx, avg_cx = _compute_file_ast_metrics(abs_p, project_root) if abs_p.is_file() else (0, 1, 1.0)
        fan_in = gctx.file_fan_in.get(fp, 0)
        blast_factor = 1.0 + math.log1p(fan_in) + 0.5 * math.log1p(max_cx)
        size_factor = max(0.5, math.log1p(max(loc, 1)) / math.log(100.0)) if loc > 0 else 1.0
        risk_score = round(
            (m["decayed_churn"] * 1.5 + m["thrash_score"] * 1.2 + m["fix_touches"] * 0.8)
            * blast_factor
            * size_factor,
            1,
        )
        scored.append({
            "filepath": fp,
            "domain": _resolve_domain_label(fp, arch_config),
            "risk_score": risk_score,
            "touches": m["touches"],
            "decayed_churn": m["decayed_churn"],
            "thrash_score": m["thrash_score"],
            "bursts": m["bursts"],
            "rework_pct": m["rework_pct"],
            "reverts": m["reverts"],
            "fix_touches": m["fix_touches"],
            "fan_in": fan_in,
            "loc": loc,
            "max_complexity": max_cx,
            "avg_complexity": avg_cx,
        })

    scored.sort(key=lambda x: (-x["risk_score"], -x["touches"], x["filepath"]))
    max_score = scored[0]["risk_score"] if scored else 0.0
    for item in scored:
        item["risk_tier"] = _assign_risk_tier(item["risk_score"], max_score)

    if target:
        sym_items = _analyze_file_symbol_hotspots(repository, project_root, target, commits=commits, limit=limit)
        return {
            "mode": "symbol" if sym_items else "file",
            "target": target,
            "file_summary": scored[0] if scored else None,
            "items": sym_items if sym_items else scored[:limit],
        }

    return {
        "mode": "file",
        "target": None,
        "file_summary": None,
        "items": scored[:limit],
    }


def analyze_coupling(
    commits_data: List[CommitRecord],
    repository,
    project_root: Path,
    scope: Optional[Union[str, List[str]]] = None,
    target: Optional[str] = None,
    limit: int = 10,
    max_bulk: int = 15,
    graph_ctx: Optional[_GraphContext] = None,
    require_exists: bool = True,
) -> Dict[str, Any]:
    include_dirs = load_include_dirs(project_root)
    exclude_patterns = load_exclude_patterns(project_root)
    scope_prefixes = normalize_scopes(scope)
    gctx = graph_ctx if graph_ctx is not None else _build_graph_context(repository)

    file_w: Dict[str, float] = defaultdict(float)
    file_cnt: Counter = Counter()
    pair_w: Dict[Tuple[str, str], float] = defaultdict(float)
    pair_cnt: Counter = Counter()
    total_w = 0.0
    qualifying_commits = 0

    for commit in commits_data:
        auditable = sorted({
            fp for fp in commit.files.keys()
            if _is_auditable_source(
                fp,
                project_root,
                include_dirs,
                exclude_patterns,
                scope_prefixes=None if target else scope_prefixes,
                require_exists=require_exists,
            )
        })
        m = len(auditable)
        if m < 2 or m > max_bulk:
            continue

        w_c = 1.0 / (m - 1)
        total_w += w_c
        qualifying_commits += 1

        for fp in auditable:
            file_w[fp] += w_c
            file_cnt[fp] += 1

        for f1, f2 in combinations(auditable, 2):
            pair_w[(f1, f2)] += w_c
            pair_cnt[(f1, f2)] += 1

    if total_w <= 0.0:
        return {"target": target, "qualifying_commits": 0, "items": []}

    min_co = 2 if (target or qualifying_commits < 20) else 3
    results: List[Dict[str, Any]] = []

    for (f1, f2), raw_cnt in pair_cnt.items():
        if raw_cnt < min_co:
            continue
        if target and f1 != target and f2 != target:
            continue
        if scope_prefixes and not target:
            if not (_matches_scope(f1, scope_prefixes) or _matches_scope(f2, scope_prefixes)):
                continue

        pw = pair_w[(f1, f2)]
        p_ab = pw / total_w
        p_a = file_w[f1] / total_w
        p_b = file_w[f2] / total_w
        lift = (p_ab / (p_a * p_b)) if (p_a > 0 and p_b > 0) else 0.0

        if not target and lift < 1.15:
            continue

        if target:
            other = f2 if f1 == target else f1
            denom = file_w[target]
            confidence = min(1.0, pw / denom) if denom > 0 else 0.0
        else:
            other = None
            denom = min(file_w[f1], file_w[f2])
            confidence = min(1.0, pw / denom) if denom > 0 else 0.0

        is_static = (f1, f2) in gctx.static_file_pairs
        coupling_type = "STRUCTURAL" if is_static else "HIDDEN"
        rank_score = (1.5 if coupling_type == "HIDDEN" else 1.0) * pw * math.log1p(max(lift, 0.0))

        item = {
            "file_a": f1,
            "file_b": f2,
            "co_commits": int(raw_cnt),
            "weighted_score": round(pw, 2),
            "confidence_pct": int(round(confidence * 100)),
            "lift": round(lift, 2),
            "coupling_type": coupling_type,
            "rank_score": round(rank_score, 3),
        }
        if other is not None:
            item["filepath"] = other
        results.append(item)

    results.sort(key=lambda x: (-x["rank_score"], -x["co_commits"], x["file_a"], x["file_b"]))
    return {
        "target": target,
        "qualifying_commits": qualifying_commits,
        "items": results[:limit],
    }


def analyze_thrash(
    commits_data: List[CommitRecord],
    project_root: Path,
    scope: Optional[Union[str, List[str]]] = None,
    target: Optional[str] = None,
    limit: int = 10,
    file_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
    require_exists: bool = True,
) -> Dict[str, Any]:
    if file_metrics is None:
        file_metrics = compute_file_evolution_metrics(
            commits_data,
            project_root,
            load_include_dirs(project_root),
            load_exclude_patterns(project_root),
            scope_prefixes=normalize_scopes(scope),
            require_exists=require_exists,
        )

    items: List[Dict[str, Any]] = []
    for fp, m in file_metrics.items():
        if target and fp != target:
            continue
        if m["touches"] < 2:
            continue
        if m["bursts"] == 0 and m["churn_balance"] < 0.35 and m["reverts"] == 0:
            continue
        items.append({
            "filepath": fp,
            "thrash_score": m["thrash_score"],
            "touches": m["touches"],
            "bursts": m["bursts"],
            "rework_pct": m["rework_pct"],
            "reverts": m["reverts"],
            "added": m["added"],
            "deleted": m["deleted"],
        })

    items.sort(key=lambda x: (-x["thrash_score"], -x["bursts"], -x["rework_pct"], x["filepath"]))
    return {"items": items[:limit]}


def analyze_growth(
    commits_data: List[CommitRecord],
    project_root: Path,
    scope: Optional[Union[str, List[str]]] = None,
    target: Optional[str] = None,
    limit: int = 10,
    file_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
    require_exists: bool = True,
) -> Dict[str, Any]:
    if file_metrics is None:
        file_metrics = compute_file_evolution_metrics(
            commits_data,
            project_root,
            load_include_dirs(project_root),
            load_exclude_patterns(project_root),
            scope_prefixes=normalize_scopes(scope),
            require_exists=require_exists,
        )

    candidates = [
        m for fp, m in file_metrics.items()
        if (not target or fp == target) and m["net_growth"] > 0
    ]
    candidates.sort(key=lambda m: (-m["net_growth"], -m["touches"], m["filepath"]))

    items: List[Dict[str, Any]] = []
    for m in candidates[: max(limit * 2, 20)]:
        fp = m["filepath"]
        abs_p = project_root / fp
        loc, max_cx, _ = _compute_file_ast_metrics(abs_p, project_root) if abs_p.is_file() else (0, 1, 1.0)
        bloat_score = round(m["net_growth"] * (1.0 + math.log1p(max_cx)), 1)
        items.append({
            "filepath": fp,
            "net_growth": m["net_growth"],
            "added": m["added"],
            "deleted": m["deleted"],
            "loc": loc,
            "max_complexity": max_cx,
            "touches": m["touches"],
            "bloat_score": bloat_score,
        })

    items.sort(key=lambda x: (-x["bloat_score"], -x["net_growth"], x["filepath"]))
    return {"items": items[:limit]}


def analyze_test_gaps(
    commits_data: List[CommitRecord],
    repository,
    project_root: Path,
    scope: Optional[Union[str, List[str]]] = None,
    target: Optional[str] = None,
    limit: int = 10,
    graph_ctx: Optional[_GraphContext] = None,
    file_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
    require_exists: bool = True,
) -> Dict[str, Any]:
    gctx = graph_ctx if graph_ctx is not None else _build_graph_context(repository)
    if file_metrics is None:
        file_metrics = compute_file_evolution_metrics(
            commits_data,
            project_root,
            load_include_dirs(project_root),
            load_exclude_patterns(project_root),
            scope_prefixes=normalize_scopes(scope),
            require_exists=require_exists,
        )

    items: List[Dict[str, Any]] = []
    for fp, m in file_metrics.items():
        if target and fp != target:
            continue
        if m["touches"] < 2:
            continue
        static_tests = gctx.file_test_callers.get(fp, 0)
        co_mod_tests = m["co_modified_tests"]
        if static_tests > 0 and co_mod_tests > 0:
            continue

        fan_in = gctx.file_fan_in.get(fp, 0)
        gap_mult = (2.0 if static_tests == 0 else 1.0) * (1.5 if co_mod_tests == 0 else 1.0)
        gap_score = round(m["decayed_churn"] * (1.0 + math.log1p(fan_in)) * gap_mult, 2)
        items.append({
            "filepath": fp,
            "gap_score": gap_score,
            "touches": m["touches"],
            "decayed_churn": m["decayed_churn"],
            "fan_in": fan_in,
            "static_test_callers": static_tests,
            "co_modified_tests": co_mod_tests,
        })

    items.sort(key=lambda x: (-x["gap_score"], -x["touches"], x["filepath"]))
    return {"items": items[:limit]}


def _resolve_target(
    repository,
    project_root: Path,
    target: Optional[str],
) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
    if not target or not target.strip():
        return "none", None, None

    raw = target.strip()
    p = Path(raw)
    if p.is_absolute():
        try:
            norm = _norm_posix(str(p.resolve().relative_to(project_root.resolve())))
        except ValueError:
            norm = _norm_posix(raw)
    else:
        norm = _norm_posix(raw)

    if (project_root / norm).is_file():
        return "file", norm, None

    if repository is not None:
        resolved_fp = repository.workspace.resolve_filepath(norm)
        if resolved_fp:
            return "file", _norm_posix(resolved_fp), None

        sym_rec = repository.graph.resolve_symbol(raw)
        if sym_rec:
            sym_fp = _norm_posix(sym_rec.get("filepath")) if sym_rec.get("filepath") else None
            return "symbol", sym_fp, sym_rec

    return "unknown", norm, None


def analyze_archaeology(
    repository,
    project_root: Path,
    target: Optional[str],
    commits: int = 100,
    limit: int = 8,
) -> Dict[str, Any]:
    if not target:
        return {"error": "target (file path or symbol) is required for 'archaeology' section.", "items": []}
    if not is_git_repo(project_root):
        return {"error": "Workspace is not a Git repository.", "items": []}

    kind, fp, sym_rec = _resolve_target(repository, project_root, target)
    if kind == "unknown" or not fp:
        return {"error": f"Could not resolve target '{target}' to an indexed symbol or file.", "items": []}

    fmt = f"{_ARCH_MARKER}%h%x1f%cs%x1f%s"
    items: List[Dict[str, Any]] = []

    if kind == "symbol" and sym_rec and sym_rec.get("start_line"):
        start_line = int(sym_rec["start_line"])
        end_line = int(sym_rec.get("end_line") or start_line)
        clean_sym = canonical_display_name(sym_rec["symbol"], sym_rec.get("name"))
        raw = _run_git(
            [
                "log",
                f"-n{int(limit)}",
                "-L",
                f"{start_line},{end_line}:{fp}",
                f"--format={fmt}",
            ],
            project_root,
        )
        if raw:
            for block in raw.split(_ARCH_MARKER):
                if not block.strip():
                    continue
                lines = block.splitlines()
                parts = lines[0].split(_FIELD_SEP, 2)
                if len(parts) < 3:
                    continue
                short_h, date_s, subject = parts[0].strip(), parts[1].strip(), parts[2].strip()
                added = 0
                deleted = 0
                for dl in lines[1:]:
                    if dl.startswith("+") and not dl.startswith("+++"):
                        added += 1
                    elif dl.startswith("-") and not dl.startswith("---"):
                        deleted += 1
                tags = []
                if _REVERT_RE.search(subject):
                    tags.append("revert")
                elif _FIX_RE.search(subject):
                    tags.append("fix")
                items.append({
                    "hash": short_h,
                    "date": date_s,
                    "added": added,
                    "deleted": deleted,
                    "tags": tags,
                    "subject": subject,
                })
        return {
            "target_kind": "symbol",
            "target_label": clean_sym,
            "filepath": fp,
            "line_range": f"L{start_line}-{end_line}" if end_line > start_line else f"L{start_line}",
            "items": items[:limit],
        }

    raw = _run_git(
        [
            "log",
            f"-n{int(min(limit, commits))}",
            "--no-merges",
            "--follow",
            "--numstat",
            f"--format={fmt}",
            "--",
            fp,
        ],
        project_root,
    )
    if raw:
        for block in raw.split(_ARCH_MARKER):
            if not block.strip():
                continue
            lines = block.splitlines()
            parts = lines[0].split(_FIELD_SEP, 2)
            if len(parts) < 3:
                continue
            short_h, date_s, subject = parts[0].strip(), parts[1].strip(), parts[2].strip()
            added, deleted = 0, 0
            for nl in lines[1:]:
                if "\t" not in nl:
                    continue
                cols = nl.split("\t", 2)
                if len(cols) >= 2 and cols[0].strip().isdigit() and cols[1].strip().isdigit():
                    added += int(cols[0].strip())
                    deleted += int(cols[1].strip())
            tags = []
            if _REVERT_RE.search(subject):
                tags.append("revert")
            elif _FIX_RE.search(subject):
                tags.append("fix")
            items.append({
                "hash": short_h,
                "date": date_s,
                "added": added,
                "deleted": deleted,
                "tags": tags,
                "subject": subject,
            })

    return {
        "target_kind": "file",
        "target_label": fp,
        "filepath": fp,
        "line_range": None,
        "items": items[:limit],
    }


def run_history_analysis(
    repository,
    project_root: Path,
    sections: List[str],
    target: Optional[str] = None,
    scope: Optional[Union[str, List[str]]] = None,
    commits: int = 100,
    limit: int = 10,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    if not is_git_repo(root):
        return {
            "is_git_repo": False,
            "commits_analyzed": 0,
            "sections": {},
        }

    needs_log = any(s in ("hotspots", "thrash", "coupling", "growth", "test_gap") for s in sections)
    needs_graph = any(s in ("hotspots", "coupling", "test_gap") for s in sections)
    needs_file_metrics = any(s in ("hotspots", "thrash", "growth", "test_gap") for s in sections)

    commits_data = parse_git_history(root, commits=commits) if needs_log else []
    graph_ctx = _build_graph_context(repository) if needs_graph else None

    target_kind, resolved_fp, _ = _resolve_target(repository, root, target)
    file_target = resolved_fp if target_kind in ("file", "symbol") else None

    include_dirs = load_include_dirs(root)
    exclude_patterns = load_exclude_patterns(root)
    scope_prefixes = normalize_scopes(scope)

    file_metrics = (
        compute_file_evolution_metrics(
            commits_data,
            root,
            include_dirs,
            exclude_patterns,
            scope_prefixes=None if file_target else scope_prefixes,
        )
        if needs_file_metrics
        else None
    )

    out_sections: Dict[str, Any] = {}
    for sec in sections:
        if sec == "hotspots":
            out_sections["hotspots"] = analyze_hotspots(
                commits_data,
                repository,
                root,
                scope=scope,
                target=file_target,
                commits=commits,
                limit=limit,
                graph_ctx=graph_ctx,
                file_metrics=file_metrics,
            )
        elif sec == "thrash":
            out_sections["thrash"] = analyze_thrash(
                commits_data,
                root,
                scope=scope,
                target=file_target,
                limit=limit,
                file_metrics=file_metrics,
            )
        elif sec == "coupling":
            out_sections["coupling"] = analyze_coupling(
                commits_data,
                repository,
                root,
                scope=scope,
                target=file_target,
                limit=limit,
                graph_ctx=graph_ctx,
            )
        elif sec == "growth":
            out_sections["growth"] = analyze_growth(
                commits_data,
                root,
                scope=scope,
                target=file_target,
                limit=limit,
                file_metrics=file_metrics,
            )
        elif sec == "test_gap":
            out_sections["test_gap"] = analyze_test_gaps(
                commits_data,
                repository,
                root,
                scope=scope,
                target=file_target,
                limit=limit,
                graph_ctx=graph_ctx,
                file_metrics=file_metrics,
            )
        elif sec == "archaeology":
            out_sections["archaeology"] = analyze_archaeology(
                repository,
                root,
                target=target,
                commits=commits,
                limit=min(limit, 12),
            )

    return {
        "is_git_repo": True,
        "commits_analyzed": len(commits_data),
        "target": target,
        "resolved_filepath": file_target,
        "scope": scope,
        "sections": out_sections,
    }


def get_file_impact_telemetry(
    repository,
    project_root: Path,
    filepath: str,
    commits: int = 100,
    coupling_limit: int = 5,
) -> Dict[str, Any]:
    if not filepath or not project_root:
        return {}
    root = Path(project_root).resolve()
    if not is_git_repo(root):
        return {}

    norm_fp = _norm_posix(filepath)
    commits_data = parse_git_history(root, commits=commits)
    if not commits_data:
        return {}

    graph_ctx = _build_graph_context(repository)
    include_dirs = load_include_dirs(root)
    exclude_patterns = load_exclude_patterns(root)
    file_metrics = compute_file_evolution_metrics(
        commits_data,
        root,
        include_dirs,
        exclude_patterns,
        scope_prefixes=None,
    )

    hotspot_res = analyze_hotspots(
        commits_data,
        repository,
        root,
        target=None,
        commits=commits,
        limit=max(len(file_metrics), 1),
        graph_ctx=graph_ctx,
        file_metrics=file_metrics,
    )
    focal_hotspot = next(
        (item for item in hotspot_res.get("items", []) if item["filepath"] == norm_fp),
        None,
    )

    coupling_res = analyze_coupling(
        commits_data,
        repository,
        root,
        target=norm_fp,
        limit=coupling_limit,
        graph_ctx=graph_ctx,
    )

    return {
        "hotspot": focal_hotspot,
        "co_changes": coupling_res.get("items", []),
    }
