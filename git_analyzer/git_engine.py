"""
Git engine module for querying and analyzing Git repositories.
Handles commit parsing, line churn, code ownership (blame), .gitignore filtering,
and folder/language code breakdowns.
"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fnmatch
import os
from pathlib import Path
import subprocess
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .models import (
    ContributorStats,
    FolderStats,
    LanguageStats,
    RepoSummary,
    TimeBucketStats,
)

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

# GitHub Linguist standard language definitions and colors
LANGUAGE_MAP: Dict[str, Tuple[str, str]] = {
    # Python
    ".py": ("Python", "#3572A5"),
    ".pyw": ("Python", "#3572A5"),
    ".ipynb": ("Jupyter Notebook", "#DA5B0B"),
    # TypeScript & JavaScript
    ".ts": ("TypeScript", "#3178c6"),
    ".tsx": ("TypeScript", "#3178c6"),
    ".js": ("JavaScript", "#f1e05a"),
    ".jsx": ("JavaScript", "#f1e05a"),
    ".mjs": ("JavaScript", "#f1e05a"),
    ".cjs": ("JavaScript", "#f1e05a"),
    # Web & Styles
    ".html": ("HTML", "#e34c26"),
    ".htm": ("HTML", "#e34c26"),
    ".css": ("CSS", "#563d7c"),
    ".scss": ("SCSS", "#c6538c"),
    ".sass": ("Sass", "#a53b70"),
    ".less": ("Less", "#1d365d"),
    ".vue": ("Vue", "#41b883"),
    ".svelte": ("Svelte", "#ff3e00"),
    # Systems & Compiled
    ".rs": ("Rust", "#dea584"),
    ".go": ("Go", "#00ADD8"),
    ".c": ("C", "#555555"),
    ".h": ("C", "#555555"),
    ".cpp": ("C++", "#f34b7d"),
    ".hpp": ("C++", "#f34b7d"),
    ".cc": ("C++", "#f34b7d"),
    ".cxx": ("C++", "#f34b7d"),
    ".cs": ("C#", "#178600"),
    ".java": ("Java", "#b07219"),
    ".kt": ("Kotlin", "#A97BFF"),
    ".kts": ("Kotlin", "#A97BFF"),
    ".swift": ("Swift", "#F05138"),
    ".m": ("Objective-C", "#438eff"),
    ".mm": ("Objective-C++", "#6866fb"),
    ".scala": ("Scala", "#c22d40"),
    # Scripting
    ".rb": ("Ruby", "#701516"),
    ".php": ("PHP", "#4F5D95"),
    ".sh": ("Shell", "#89e051"),
    ".bash": ("Shell", "#89e051"),
    ".zsh": ("Shell", "#89e051"),
    ".ps1": ("PowerShell", "#012456"),
    ".psm1": ("PowerShell", "#012456"),
    ".lua": ("Lua", "#000080"),
    ".pl": ("Perl", "#0298c3"),
    ".r": ("R", "#198CE7"),
    ".dart": ("Dart", "#00B4AB"),
    # Data & Config
    ".sql": ("SQL", "#e38c00"),
    ".json": ("JSON", "#292929"),
    ".yaml": ("YAML", "#cb171e"),
    ".yml": ("YAML", "#cb171e"),
    ".toml": ("TOML", "#9c4221"),
    ".xml": ("XML", "#0060ac"),
    ".md": ("Markdown", "#083fa1"),
    ".markdown": ("Markdown", "#083fa1"),
    ".dockerfile": ("Dockerfile", "#384d54"),
    ".graphql": ("GraphQL", "#e10098"),
    ".proto": ("Protocol Buffer", "#4f8d6c"),
}


def run_git_command(args: List[str], cwd: str, stdin_data: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a git command in the specified directory safely with utf-8 decoding."""
    cmd = ["git", "-C", str(cwd), "-c", "core.quotepath=false"] + args
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )


def clean_git_path(filepath: str) -> str:
    """Normalize and unquote a git file path, decoding any octal escapes."""
    p = filepath.strip()
    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
        p = p[1:-1]
        try:
            p = p.encode("latin1").decode("unicode_escape").encode("latin1").decode("utf-8")
        except Exception:
            pass
    p = p.strip('"\'')
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.strip("/")


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
        res = run_git_command(["ls-files"], cwd=repo_path)
        if res.returncode != 0:
            return []
    files = [clean_git_path(f) for f in res.stdout.splitlines() if f.strip()]
    return files


def query_git_ignored_files(repo_path: str, filepaths: Iterable[str]) -> Set[str]:
    """
    Query Git's native engine to check which filepaths match .gitignore rules.
    Uses git check-ignore --no-index -z --stdin for batch testing.
    """
    paths_list = [clean_git_path(p) for p in filepaths if p]
    if not paths_list:
        return set()

    stdin_payload = "\0".join(paths_list) + "\0"
    res = run_git_command(
        ["check-ignore", "--no-index", "-z", "--stdin"],
        cwd=repo_path,
        stdin_data=stdin_payload
    )

    if res.stdout:
        return set(clean_git_path(x) for x in res.stdout.split("\0") if x)
    return set()


def should_ignore_path(
    filepath: str,
    custom_patterns: Optional[List[str]] = None,
    ignored_by_git: Optional[Set[str]] = None
) -> bool:
    """Determine if a file path should be ignored based on .gitignore or custom patterns."""
    norm_path = clean_git_path(filepath)
    if not norm_path:
        return False

    filename = Path(norm_path).name

    if ignored_by_git and norm_path in ignored_by_git:
        return True

    if custom_patterns:
        for raw_pattern in custom_patterns:
            pat = raw_pattern.replace("\\", "/").strip().strip('"\'').lstrip("./")
            if not pat:
                continue

            # Exact match on full path or filename
            if norm_path == pat or filename == pat:
                return True

            # Directory pattern matching (e.g. "docs/*", "docs/", or "docs")
            if pat.endswith("/*"):
                dir_pat = pat[:-2].rstrip("/")
                if norm_path == dir_pat or norm_path.startswith(dir_pat + "/"):
                    return True
            elif pat.endswith("/"):
                dir_pat = pat.rstrip("/")
                if norm_path == dir_pat or norm_path.startswith(dir_pat + "/"):
                    return True
            elif not any(c in pat for c in "*?[]"):
                if norm_path == pat or norm_path.startswith(pat + "/"):
                    return True

            # Glob pattern match
            if fnmatch.fnmatch(norm_path, pat) or fnmatch.fnmatch(filename, pat):
                return True

            # Match sub-folder wildcard pattern (e.g. "test/*.py" matching "foo/test/bar.py")
            if not pat.startswith("*") and not pat.startswith("/"):
                if fnmatch.fnmatch(norm_path, f"*/{pat}"):
                    return True

    return False


def is_smart_eligible_file(
    filepath: str,
    allowed_extensions: Optional[Set[str]] = None,
    smart_filter: bool = True
) -> bool:
    """Check if file should be blamed based on smart filtering or extension constraints."""
    norm_path = clean_git_path(filepath)
    ext = Path(norm_path).suffix.lower()

    if allowed_extensions is not None:
        return ext in allowed_extensions

    if not smart_filter:
        return True

    if ext in IGNORED_EXTENSIONS:
        return False

    filename = Path(norm_path).name
    for pattern in IGNORED_PATTERNS:
        if "/" in pattern:
            if fnmatch.fnmatch(norm_path, pattern):
                return False
        else:
            if fnmatch.fnmatch(filename, pattern):
                return False

    return True


def get_folder_group(filepath: str) -> str:
    """Determine the top-level folder group for a file (VSCodeCounter style)."""
    norm = clean_git_path(filepath)
    parts = norm.split("/")
    if len(parts) <= 1:
        return "(root)"
    # If the root folder is a container directory like src, lib, app, packages
    if parts[0] in ("src", "lib", "app", "packages", "pkg") and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}/"
    return f"{parts[0]}/"


def detect_file_language(filepath: str) -> Tuple[str, str]:
    """Identify the programming/markup language and its GitHub color."""
    norm = clean_git_path(filepath)
    ext = Path(norm).suffix.lower()
    filename = Path(norm).name.lower()
    if filename in ("dockerfile", "containerfile"):
        return ("Dockerfile", "#384d54")
    if ext in LANGUAGE_MAP:
        return LANGUAGE_MAP[ext]
    if ext:
        lang_name = ext.lstrip(".").upper()
        return (lang_name, "#8b949e")
    return ("Other", "#8b949e")


def compute_code_breakdowns(
    file_line_counts: Dict[str, int]
) -> Tuple[List[FolderStats], List[LanguageStats]]:
    """Compute folder-level line counts and language distribution."""
    folder_lines: Dict[str, int] = defaultdict(int)
    folder_files: Dict[str, int] = defaultdict(int)
    lang_lines: Dict[str, int] = defaultdict(int)
    lang_files: Dict[str, int] = defaultdict(int)
    lang_colors: Dict[str, str] = {}

    for fpath, lcount in file_line_counts.items():
        fg = get_folder_group(fpath)
        folder_lines[fg] += lcount
        folder_files[fg] += 1

        lname, lcolor = detect_file_language(fpath)
        lang_lines[lname] += lcount
        lang_files[lname] += 1
        lang_colors[lname] = lcolor

    folder_stats = [
        FolderStats(folder_path=fg, lines=folder_lines[fg], files_count=folder_files[fg])
        for fg in sorted(folder_lines.keys(), key=lambda k: folder_lines[k], reverse=True)
    ]

    language_stats = [
        LanguageStats(name=lg, color=lang_colors[lg], lines=lang_lines[lg], files_count=lang_files[lg])
        for lg in sorted(lang_lines.keys(), key=lambda k: lang_lines[k], reverse=True)
    ]

    return folder_stats, language_stats


def count_file_lines_quick(repo_path: str, filepath: str, branch: str = "HEAD") -> int:
    """Fast line counting for a file from working tree or git show."""
    norm = clean_git_path(filepath)
    full_path = os.path.join(repo_path, norm)
    try:
        with open(full_path, "rb") as f:
            return f.read().count(b"\n")
    except Exception:
        res = run_git_command(["show", f"{branch}:{norm}"], cwd=repo_path)
        if res.returncode == 0:
            return res.stdout.count("\n")
        return 0


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
    Tracks additions, deletions, and commits both in total and per contributor along time.
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
                if " => " in filepath:
                    if "{" in filepath and "}" in filepath:
                        pre, rest = filepath.split("{", 1)
                        mid, post = rest.split("}", 1)
                        filepath = pre + mid.split(" => ")[-1] + post
                    else:
                        filepath = filepath.split(" => ")[-1]

                filepath = clean_git_path(filepath)
                current_commit["files"].append((add_str, del_str, filepath))
                all_touched_files.add(filepath)

    git_ignored = query_git_ignored_files(repo_path, all_touched_files) if respect_gitignore else set()

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

        valid_files = [
            (adds, dels, path)
            for adds, dels, path in files
            if not should_ignore_path(path, custom_ignore_patterns, git_ignored)
        ]

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
                author_commits=defaultdict(int),
                author_additions=defaultdict(int),
                author_deletions=defaultdict(int)
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
                bucket.author_additions[author_key] = bucket.author_additions.get(author_key, 0) + adds
                bucket.author_deletions[author_key] = bucket.author_deletions.get(author_key, 0) + dels

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
    norm = clean_git_path(filepath)
    res = run_git_command(
        ["blame", "--line-porcelain", branch, "--", norm],
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
) -> Tuple[Dict[str, int], Dict[str, int], int, int]:
    """
    Run parallel git blame across tracked files to compute current line ownership
    and individual file line counts.
    Returns:
        (author_lines, file_line_counts, total_eligible, total_files)
    """
    all_files = get_tracked_files(repo_path, branch)
    total_files = len(all_files)
    if total_files == 0:
        return {}, {}, 0, 0

    git_ignored = query_git_ignored_files(repo_path, all_files) if respect_gitignore else set()

    eligible_files = [
        f for f in all_files
        if not should_ignore_path(f, custom_ignore_patterns, git_ignored)
        and is_smart_eligible_file(f, allowed_extensions, smart_filter)
    ]

    total_eligible = len(eligible_files)
    if total_eligible == 0:
        return {}, {}, 0, total_files

    author_lines: Dict[str, int] = defaultdict(int)
    file_lines: Dict[str, int] = {}
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
                f_total = sum(file_counts.values())
                file_lines[filepath] = f_total
                for author, count in file_counts.items():
                    author_lines[author] += count
            except Exception:
                pass
            finally:
                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total_eligible, filepath)

    return dict(author_lines), file_lines, total_eligible, total_files


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
    file_lines: Dict[str, int] = {}

    if not no_blame:
        blame_counts, file_lines, blamed_count, total_files = compute_blame_stats(
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
    else:
        # Quick line count without blame
        all_files = get_tracked_files(repo_path, actual_branch)
        total_files = len(all_files)
        git_ignored = query_git_ignored_files(repo_path, all_files) if respect_gitignore else set()
        eligible_files = [
            f for f in all_files
            if not should_ignore_path(f, custom_ignore_patterns, git_ignored)
            and is_smart_eligible_file(f, allowed_extensions, smart_filter)
        ]
        blamed_count = len(eligible_files)
        for ef in eligible_files:
            file_lines[ef] = count_file_lines_quick(repo_path, ef, actual_branch)
        total_current_lines = sum(file_lines.values())

    folder_stats, language_stats = compute_code_breakdowns(file_lines)

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
        folder_stats=folder_stats,
        language_stats=language_stats,
        blame_skipped=no_blame,
        blamed_files_count=blamed_count,
        total_files_count=total_files
    )
