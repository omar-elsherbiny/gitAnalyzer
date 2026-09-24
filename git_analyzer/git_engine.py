"""
Git engine module for querying and analyzing Git repositories.
Handles commit parsing, line churn, code ownership (blame), and .gitignore/pattern filtering.
"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fnmatch
import os
from pathlib import Path
import subprocess
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .models import ContributorStats, RepoSummary, TimeBucketStats

# Common binary or non-code extensions to ignore in smart mode
IGNORED_EXTENSIONS = {
    # Images / Media
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg", ".tiff",
    ".mp3", ".wav", ".ogg", ".mp4", ".avi", ".mov", ".mkv", ".flv", ".webm",
    # Documents / Binaries
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso", ".dmg",
    ".pyc", ".pyo", ".pyd", ".class", ".jar", ".war",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Data / DB / ML models
    ".db", ".sqlite", ".sqlite3", ".parquet", ".pkl", ".pickle",
    ".onnx", ".pt", ".pth", ".h5", ".weights"
}

# Common lockfiles, minified files, and generated folders to ignore in smart mode
IGNORED_PATTERNS = [
    # Lockfiles
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "go.sum", "flake.lock",
    "bun.lockb",
    # Minified & bundles
    "*.min.js", "*.min.css", "*.bundle.js", "*.bundle.css", "*.map",
    # Common build/vendor dirs (even if tracked)
    "node_modules/*", "vendor/*", "dist/*", "build/*", ".next/*", ".nuxt/*",
    ".venv/*", "venv/*", "env/*", "__pycache__/*"
]


def run_git_command(args: List[str], cwd: str, stdin_data: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a git command in the specified directory safely with utf-8 decoding."""
    cmd = ["git", "-C", str(cwd)] + args
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )


def check_git_installed() -> bool:
    """Verify that git CLI is available on PATH."""
    try:
        res = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        return res.returncode == 0
    except FileNotFoundError:
        return False


def is_git_repo(path: str) -> bool:
    """Verify that the target path is inside a Git repository work tree."""
    res = run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return res.returncode == 0 and res.stdout.strip() == "true"


def get_git_root(path: str) -> str:
    """Get the top-level directory of the Git repository."""
    res = run_git_command(["rev-parse", "--show-toplevel"], cwd=path)
    if res.returncode == 0:
        return res.stdout.strip()
    return path


def get_current_branch(repo_path: str) -> str:
    """Get the current branch or revision description."""
    res = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    if res.returncode == 0:
        branch = res.stdout.strip()
        if branch == "HEAD":
            # Detached head, get short hash
            short_res = run_git_command(["rev-parse", "--short", "HEAD"], cwd=repo_path)
            return f"HEAD ({short_res.stdout.strip()})" if short_res.returncode == 0 else "HEAD"
        return branch
    return "unknown"


def is_repo_empty(repo_path: str) -> bool:
    """Check if the repository has any commits."""
    res = run_git_command(["rev-parse", "--verify", "HEAD"], cwd=repo_path)
    return res.returncode != 0


def get_head_commit_info(repo_path: str, branch: str = "HEAD") -> Tuple[str, str, str, Optional[datetime]]:
    """Retrieve hash, message, author, and datetime of the target commit/branch."""
    res = run_git_command(
        ["log", "-1", branch, "--format=%h|%s|%an|%aI"],
        cwd=repo_path
    )
    if res.returncode != 0 or not res.stdout.strip():
        return "", "", "", None

    parts = res.stdout.strip().split("|", 3)
    short_hash = parts[0] if len(parts) > 0 else ""
    message = parts[1] if len(parts) > 1 else ""
    author = parts[2] if len(parts) > 2 else ""
    dt = None
    if len(parts) > 3 and parts[3]:
        try:
            dt = datetime.fromisoformat(parts[3])
        except Exception:
            pass
    return short_hash, message, author, dt


def get_tracked_files(repo_path: str, branch: str = "HEAD") -> List[str]:
    """Retrieve list of all tracked files in the given branch/commit."""
    res = run_git_command(["ls-tree", "-r", "--name-only", branch], cwd=repo_path)
    if res.returncode != 0:
        # Fallback to ls-files if ls-tree fails
        res = run_git_command(["ls-files"], cwd=repo_path)
        if res.returncode != 0:
            return []
    files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
    return files


def query_git_ignored_files(repo_path: str, filepaths: Iterable[str]) -> Set[str]:
    """
    Query Git's native engine to check which filepaths match .gitignore rules.
    Uses git check-ignore --no-index -z --stdin for batch testing.
    """
    paths_list = [p.replace("\\", "/").lstrip("./") for p in filepaths if p]
    if not paths_list:
        return set()

    stdin_payload = "\0".join(paths_list) + "\0"
    res = run_git_command(
        ["check-ignore", "--no-index", "-z", "--stdin"],
        cwd=repo_path,
        stdin_data=stdin_payload
    )

    if res.stdout:
        return set(x for x in res.stdout.split("\0") if x)
    return set()


def should_ignore_path(
    filepath: str,
    custom_patterns: Optional[List[str]] = None,
    ignored_by_git: Optional[Set[str]] = None
) -> bool:
    """
    Determine if a file path should be ignored based on:
    1. .gitignore rules
    2. User-specified custom ignore patterns (--ignore / --exclude)
    """
    norm_path = filepath.replace("\\", "/").lstrip("./")
    filename = Path(filepath).name

    # 1. Match against .gitignore
    if ignored_by_git and norm_path in ignored_by_git:
        return True

    # 2. Match against custom user patterns
    if custom_patterns:
        for raw_pattern in custom_patterns:
            pat = raw_pattern.replace("\\", "/").strip().lstrip("./")
            if not pat:
                continue

            # Strip trailing slash for directory comparison
            dir_pat = pat.rstrip("/")
            if norm_path == dir_pat or norm_path.startswith(dir_pat + "/"):
                return True

            # Match wildcard on full relative path or filename
            if fnmatch.fnmatch(norm_path, pat) or fnmatch.fnmatch(filename, pat):
                return True

    return False


def is_smart_eligible_file(
    filepath: str,
    allowed_extensions: Optional[Set[str]] = None,
    smart_filter: bool = True
) -> bool:
    """Check if file should be blamed based on smart filtering or extension constraints."""
    norm_path = filepath.replace("\\", "/").lstrip("./")
    ext = Path(filepath).suffix.lower()

    if allowed_extensions is not None:
        return ext in allowed_extensions

    if not smart_filter:
        return True

    # Check extension
    if ext in IGNORED_EXTENSIONS:
        return False

    # Check against smart ignored patterns
    filename = Path(filepath).name
    for pattern in IGNORED_PATTERNS:
        if "/" in pattern:
            if fnmatch.fnmatch(norm_path, pattern):
                return False
        else:
            if fnmatch.fnmatch(filename, pattern):
                return False

    return True


def parse_commit_history(
    repo_path: str,
    branch: str = "HEAD",
    since: Optional[str] = None,
    until: Optional[str] = None,
    by_email: bool = False,
    custom_ignore_patterns: Optional[List[str]] = None,
    respect_gitignore: bool = True
) -> Tuple[Dict[str, ContributorStats], List[TimeBucketStats], int, int, int]:
    """
    Parse commit logs with --numstat and mailmap.
    Filters files against .gitignore and custom ignore patterns.
    """
    cmd = [
        "log",
        branch,
        "--use-mailmap",
        "--numstat",
        "--date=iso-strict",
        "--format=COMMIT|%H|%aN|%aE|%at|%aI"
    ]
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")

    res = run_git_command(cmd, cwd=repo_path)
    if res.returncode != 0:
        return {}, [], 0, 0, 0

    # First pass: parse commits and gather all touched file paths
    raw_commits = []
    current_commit = None
    all_touched_files = set()

    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("COMMIT|"):
            parts = line.split("|")
            commit_hash = parts[1] if len(parts) > 1 else ""
            author_name = parts[2] if len(parts) > 2 else "Unknown"
            author_email = parts[3] if len(parts) > 3 else ""
            epoch_time = float(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0.0
            iso_str = parts[5] if len(parts) > 5 else ""

            try:
                commit_dt = datetime.fromisoformat(iso_str)
            except Exception:
                commit_dt = datetime.fromtimestamp(epoch_time, tz=timezone.utc)

            current_commit = {
                "hash": commit_hash,
                "name": author_name,
                "email": author_email,
                "epoch": epoch_time,
                "dt": commit_dt,
                "files": []
            }
            raw_commits.append(current_commit)
        elif current_commit is not None:
            parts = line.split("\t")
            if len(parts) >= 3:
                add_str, del_str, filepath = parts[0].strip(), parts[1].strip(), parts[2].strip()
                # Handle rename format e.g. "path/{old => new}/file.py"
                if " => " in filepath:
                    if "{" in filepath and "}" in filepath:
                        pre, rest = filepath.split("{", 1)
                        mid, post = rest.split("}", 1)
                        filepath = pre + mid.split(" => ")[-1] + post
                    else:
                        filepath = filepath.split(" => ")[-1]

                current_commit["files"].append((add_str, del_str, filepath))
                all_touched_files.add(filepath)

    # Check gitignore for all touched files
    git_ignored = query_git_ignored_files(repo_path, all_touched_files) if respect_gitignore else set()

    # Second pass: compute stats for non-ignored files
    contributors: Dict[str, ContributorStats] = {}
    weekly_buckets: Dict[Tuple[int, int], TimeBucketStats] = {}
    total_commits = 0
    total_additions = 0
    total_deletions = 0

    has_filter = bool(custom_ignore_patterns) or bool(git_ignored)

    for c in raw_commits:
        author_name = c["name"]
        author_email = c["email"]
        commit_dt = c["dt"]
        epoch_time = c["epoch"]
        files = c["files"]

        # Filter out ignored files
        valid_files = [
            (adds, dels, path)
            for adds, dels, path in files
            if not should_ignore_path(path, custom_ignore_patterns, git_ignored)
        ]

        # If file filtering is active and commit has files, but all files were ignored, skip commit
        if has_filter and files and not valid_files:
            continue

        total_commits += 1

        author_key = author_email.lower() if by_email and author_email else author_name
        if author_key not in contributors:
            contributors[author_key] = ContributorStats(
                name=author_name,
                email=author_email
            )

        contrib = contributors[author_key]
        contrib.commits += 1

        if contrib.first_commit_date is None or commit_dt < contrib.first_commit_date:
            contrib.first_commit_date = commit_dt
        if contrib.last_commit_date is None or commit_dt > contrib.last_commit_date:
            contrib.last_commit_date = commit_dt

        # Prepare weekly bucket
        cal = commit_dt.isocalendar()
        bucket_key = (cal.year, cal.week)
        if bucket_key not in weekly_buckets:
            period_label = f"{cal.year}-W{cal.week:02d}"
            weekly_buckets[bucket_key] = TimeBucketStats(
                period_label=period_label,
                timestamp=epoch_time,
                commits=0,
                additions=0,
                deletions=0,
                author_commits=defaultdict(int)
            )

        bucket = weekly_buckets[bucket_key]
        bucket.commits += 1
        bucket.author_commits[author_key] = bucket.author_commits.get(author_key, 0) + 1

        for add_str, del_str, _ in valid_files:
            if add_str.isdigit() and del_str.isdigit():
                adds = int(add_str)
                dels = int(del_str)
                contrib.additions += adds
                contrib.deletions += dels
                total_additions += adds
                total_deletions += dels
                bucket.additions += adds
                bucket.deletions += dels

    time_series = [
        weekly_buckets[k] for k in sorted(weekly_buckets.keys())
    ]

    return contributors, time_series, total_commits, total_additions, total_deletions


def _blame_single_file(
    repo_path: str,
    filepath: str,
    branch: str = "HEAD",
    by_email: bool = False
) -> Dict[str, int]:
    """Blame a single file and return mapping of author_key -> line count."""
    res = run_git_command(
        ["blame", "--line-porcelain", branch, "--", filepath],
        cwd=repo_path
    )
    if res.returncode != 0:
        return {}

    file_line_counts: Dict[str, int] = defaultdict(int)
    for line in res.stdout.splitlines():
        if by_email:
            if line.startswith("author-mail "):
                mail = line[12:].strip().strip("<>").lower()
                if mail:
                    file_line_counts[mail] += 1
        else:
            if line.startswith("author "):
                name = line[7:].strip()
                if name:
                    file_line_counts[name] += 1

    return dict(file_line_counts)


def compute_blame_stats(
    repo_path: str,
    branch: str = "HEAD",
    by_email: bool = False,
    smart_filter: bool = True,
    allowed_extensions: Optional[Set[str]] = None,
    custom_ignore_patterns: Optional[List[str]] = None,
    respect_gitignore: bool = True,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    max_workers: int = 16
) -> Tuple[Dict[str, int], int, int]:
    """
    Run parallel git blame across tracked files to compute current line ownership.
    Respects .gitignore rules, custom ignore patterns, and smart filtering.
    """
    all_files = get_tracked_files(repo_path, branch)
    total_files = len(all_files)
    if total_files == 0:
        return {}, 0, 0

    # Query .gitignore for tracked files
    git_ignored = query_git_ignored_files(repo_path, all_files) if respect_gitignore else set()

    # Filter files: exclude gitignored, custom ignored, smart ignored, or non-matching extensions
    eligible_files = [
        f for f in all_files
        if not should_ignore_path(f, custom_ignore_patterns, git_ignored)
        and is_smart_eligible_file(f, allowed_extensions, smart_filter)
    ]

    total_eligible = len(eligible_files)
    if total_eligible == 0:
        return {}, 0, total_files

    author_lines: Dict[str, int] = defaultdict(int)
    completed_count = 0

    workers = min(max_workers, max(1, total_eligible))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_file = {
            executor.submit(_blame_single_file, repo_path, f, branch, by_email): f
            for f in eligible_files
        }

        for future in as_completed(future_to_file):
            filepath = future_to_file[future]
            try:
                file_counts = future.result()
                for author, count in file_counts.items():
                    author_lines[author] += count
            except Exception:
                pass
            finally:
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total_eligible, filepath)

    return dict(author_lines), total_eligible, total_files


def analyze_repository(
    repo_path: str,
    branch: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    by_email: bool = False,
    no_blame: bool = False,
    smart_filter: bool = True,
    allowed_extensions: Optional[Set[str]] = None,
    custom_ignore_patterns: Optional[List[str]] = None,
    respect_gitignore: bool = True,
    blame_progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> RepoSummary:
    """Analyze repository and produce complete RepoSummary."""
    if not check_git_installed():
        raise RuntimeError("Git CLI is not installed or not found on PATH.")

    repo_path = str(Path(repo_path).resolve())
    if not is_git_repo(repo_path):
        raise ValueError(f"Directory is not a valid Git repository: {repo_path}")

    root_dir = get_git_root(repo_path)
    repo_name = Path(root_dir).name
    actual_branch = branch if branch else get_current_branch(repo_path)

    if is_repo_empty(repo_path):
        return RepoSummary(
            repo_path=root_dir,
            repo_name=repo_name,
            current_branch=actual_branch
        )

    head_hash, head_msg, head_author, head_dt = get_head_commit_info(
        repo_path, actual_branch
    )

    contributors, time_series, total_commits, total_adds, total_dels = parse_commit_history(
        repo_path=repo_path,
        branch=actual_branch,
        since=since,
        until=until,
        by_email=by_email,
        custom_ignore_patterns=custom_ignore_patterns,
        respect_gitignore=respect_gitignore
    )

    first_date = min((c.first_commit_date for c in contributors.values() if c.first_commit_date), default=None)
    last_date = max((c.last_commit_date for c in contributors.values() if c.last_commit_date), default=None)

    total_current_lines = 0
    blamed_count = 0
    total_files = 0

    if not no_blame:
        blame_counts, blamed_count, total_files = compute_blame_stats(
            repo_path=repo_path,
            branch=actual_branch,
            by_email=by_email,
            smart_filter=smart_filter,
            allowed_extensions=allowed_extensions,
            custom_ignore_patterns=custom_ignore_patterns,
            respect_gitignore=respect_gitignore,
            progress_callback=blame_progress_callback
        )

        total_current_lines = sum(blame_counts.values())

        for author_key, lines in blame_counts.items():
            if author_key in contributors:
                contributors[author_key].current_lines = lines
            else:
                new_contrib = ContributorStats(
                    name=author_key,
                    email=author_key if by_email else "",
                    current_lines=lines
                )
                contributors[author_key] = new_contrib

    return RepoSummary(
        repo_path=root_dir,
        repo_name=repo_name,
        current_branch=actual_branch,
        head_hash=head_hash,
        head_message=head_msg,
        head_author=head_author,
        head_date=head_dt,
        total_commits=total_commits,
        total_additions=total_adds,
        total_deletions=total_dels,
        total_current_lines=total_current_lines,
        first_commit_date=first_date,
        last_commit_date=last_date,
        contributors=contributors,
        time_series=time_series,
        blame_skipped=no_blame,
        blamed_files_count=blamed_count,
        total_files_count=total_files
    )
