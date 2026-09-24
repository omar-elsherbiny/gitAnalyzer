"""
CLI interface and execution entrypoint for GitAnalyzer.
"""

import argparse
from datetime import datetime
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Ensure UTF-8 output encoding across Windows shells
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .cli_formatter import (
    print_contributors_table,
    print_folder_distribution,
    print_footer_tips,
    print_header,
    print_language_distribution,
    print_summary_cards,
)
from .git_engine import analyze_repository
from .models import RepoSummary
from .visualizer import plot_contributions

console = Console()


def repo_summary_to_dict(summary: RepoSummary) -> Dict[str, Any]:
    """Convert RepoSummary to serializable dict for JSON export."""
    return {
        "repository": {
            "name": summary.repo_name,
            "path": summary.repo_path,
            "branch": summary.current_branch,
            "head_hash": summary.head_hash,
            "head_message": summary.head_message,
            "head_author": summary.head_author,
            "head_date": summary.head_date.isoformat() if summary.head_date else None,
        },
        "overview": {
            "total_commits": summary.total_commits,
            "total_additions": summary.total_additions,
            "total_deletions": summary.total_deletions,
            "total_net_lines": summary.total_net_lines,
            "total_current_lines": summary.total_current_lines,
            "first_commit_date": summary.first_commit_date.isoformat() if summary.first_commit_date else None,
            "last_commit_date": summary.last_commit_date.isoformat() if summary.last_commit_date else None,
            "blame_skipped": summary.blame_skipped,
            "blamed_files_count": summary.blamed_files_count,
            "total_files_count": summary.total_files_count,
        },
        "folders": [
            {
                "folder": f.folder_path,
                "files_count": f.files_count,
                "lines": f.lines,
            }
            for f in summary.folder_stats
        ],
        "languages": [
            {
                "name": lang.name,
                "color": lang.color,
                "files_count": lang.files_count,
                "lines": lang.lines,
            }
            for lang in summary.language_stats
        ],
        "contributors": [
            {
                "name": c.name,
                "email": c.email,
                "commits": c.commits,
                "additions": c.additions,
                "deletions": c.deletions,
                "net_lines": c.net_lines,
                "churn": c.churn,
                "current_lines": c.current_lines,
                "first_commit_date": c.first_commit_date.isoformat() if c.first_commit_date else None,
                "last_commit_date": c.last_commit_date.isoformat() if c.last_commit_date else None,
            }
            for c in sorted(summary.contributors.values(), key=lambda x: x.commits, reverse=True)
        ],
        "time_series": [
            {
                "period": pt.period_label,
                "timestamp": pt.timestamp,
                "commits": pt.commits,
                "additions": pt.additions,
                "deletions": pt.deletions,
            }
            for pt in summary.time_series
        ]
    }


def parse_args(args=None):
    """Parse command-line arguments with intuitive help categories and examples."""
    parser = argparse.ArgumentParser(
        prog="gitanalyzer",
        description="⚡ GitAnalyzer - Local Git Repository Contributor Insights & Code Ownership",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
QUICK CHEATSHEET & COMMON EXAMPLES:
  gitanalyzer                            Analyze current repo
  gitanalyzer C:/path/to/my-repo          Analyze specific repository path
  gitanalyzer -p                         Pop up interactive GitHub-style activity graph
  gitanalyzer --save-plot chart.png      Export activity graph to PNG without opening window
  gitanalyzer -i "tests/*" "docs/*"      Ignore tests and documentation folders
  gitanalyzer --sort lines               Rank contributors by surviving code lines (ownership)
  gitanalyzer --since "3 months ago"     Analyze recent sprint or quarter activity
  gitanalyzer --no-blame                 Instant summary on massive repositories (skips blame)
  gitanalyzer --json > report.json       Export full analysis to JSON
        """
    )

    parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to Git repository directory (default: current directory '.')"
    )

    group_repo = parser.add_argument_group("Repository & Revision Scope")
    group_repo.add_argument(
        "-b", "--branch",
        metavar="REF",
        default=None,
        help="Target branch, tag, or commit ref to inspect (default: active branch / HEAD)"
    )
    group_repo.add_argument(
        "-s", "--since",
        metavar="DATE/REF",
        default=None,
        help="Include commits after date or ref (e.g. '2024-01-01', '3 months ago')"
    )
    group_repo.add_argument(
        "-u", "--until",
        metavar="DATE/REF",
        default=None,
        help="Include commits before date or ref (e.g. '2024-12-31')"
    )

    group_filter = parser.add_argument_group("File Filtering & Exclusions")
    group_filter.add_argument(
        "-i", "--ignore", "--exclude",
        dest="ignore",
        nargs="+",
        metavar="PATTERN",
        default=None,
        help="Skip files or folders matching patterns (e.g. -i 'tests/*' 'docs/' '*.min.js')"
    )
    group_filter.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Do not ignore files matched by .gitignore (.gitignore is respected by default)"
    )
    group_filter.add_argument(
        "-e", "--ext",
        nargs="+",
        metavar="EXT",
        default=None,
        help="Only calculate code ownership for specific file extensions (e.g. -e .py .js .ts)"
    )
    group_filter.add_argument(
        "--all-files",
        action="store_true",
        help="Blame all tracked files (disables smart filtering of lockfiles & binaries)"
    )
    group_filter.add_argument(
        "--no-blame",
        action="store_true",
        help="Skip git blame ownership analysis entirely (instant execution on huge repos)"
    )

    group_contrib = parser.add_argument_group("Contributor Display")
    group_contrib.add_argument(
        "--sort",
        choices=["commits", "additions", "deletions", "lines", "net", "churn"],
        default="commits",
        help="Sort contributor table by metric (default: 'commits')"
    )
    group_contrib.add_argument(
        "--top",
        type=int,
        metavar="N",
        default=20,
        help="Number of top contributors to show in table (default: 20, use 0 for all)"
    )
    group_contrib.add_argument(
        "--by-email",
        action="store_true",
        help="Identify and group contributors by author email instead of name"
    )

    group_output = parser.add_argument_group("Output & Visualization")
    group_output.add_argument(
        "-p", "--plot",
        action="store_true",
        help="Open interactive Matplotlib contribution & activity graph window"
    )
    group_output.add_argument(
        "--save-plot",
        metavar="FILEPATH",
        default=None,
        help="Export Matplotlib contribution graph to image file (e.g. contributions.png)"
    )
    group_output.add_argument(
        "--json",
        action="store_true",
        help="Output full analysis results as structured JSON"
    )
    group_output.add_argument(
        "-w", "--workers",
        type=int,
        metavar="N",
        default=16,
        help="Number of worker threads for parallel git blame (default: 16)"
    )

    return parser.parse_args(args)


def flatten_ignore_patterns(raw_patterns: Optional[List[str]]) -> List[str]:
    """Flatten space-separated and comma-separated ignore patterns."""
    if not raw_patterns:
        return []
    result = []
    for item in raw_patterns:
        for sub in item.split(","):
            cleaned = sub.strip().strip('"\'')
            if cleaned:
                result.append(cleaned)
    return result


def main(args=None):
    parsed = parse_args(args)

    allowed_exts = None
    if parsed.ext:
        allowed_exts = {e if e.startswith(".") else f".{e}" for e in parsed.ext}

    ignore_patterns = flatten_ignore_patterns(parsed.ignore)
    respect_gitignore = not parsed.no_gitignore

    progress = None
    task_id = None

    def blame_progress_callback(completed: int, total: int, current_file: str):
        nonlocal progress, task_id
        if not parsed.json and progress and task_id is not None:
            short_name = os.path.basename(current_file)
            progress.update(
                task_id,
                completed=completed,
                total=total,
                description=f"[cyan]Analyzing code ownership...[/cyan] [dim]({short_name})[/dim]"
            )

    try:
        if not parsed.json and not parsed.no_blame:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(complete_style="magenta", finished_style="green"),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True
            ) as prg:
                progress = prg
                task_id = prg.add_task("[cyan]Scanning repository files...", total=100)
                summary = analyze_repository(
                    repo_path=parsed.repo_path,
                    branch=parsed.branch,
                    since=parsed.since,
                    until=parsed.until,
                    by_email=parsed.by_email,
                    no_blame=parsed.no_blame,
                    smart_filter=not parsed.all_files,
                    allowed_extensions=allowed_exts,
                    custom_ignore_patterns=ignore_patterns,
                    respect_gitignore=respect_gitignore,
                    blame_progress_callback=blame_progress_callback
                )
        else:
            summary = analyze_repository(
                repo_path=parsed.repo_path,
                branch=parsed.branch,
                since=parsed.since,
                until=parsed.until,
                by_email=parsed.by_email,
                no_blame=parsed.no_blame,
                smart_filter=not parsed.all_files,
                allowed_extensions=allowed_exts,
                custom_ignore_patterns=ignore_patterns,
                respect_gitignore=respect_gitignore,
                blame_progress_callback=None
            )

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    if parsed.json:
        data = repo_summary_to_dict(summary)
        print(json.dumps(data, indent=2))
        return

    filter_parts = []
    if parsed.branch:
        filter_parts.append(f"branch={parsed.branch}")
    if parsed.since:
        filter_parts.append(f"since={parsed.since}")
    if parsed.until:
        filter_parts.append(f"until={parsed.until}")
    if allowed_exts:
        filter_parts.append(f"extensions={', '.join(sorted(allowed_exts))}")
    if ignore_patterns:
        filter_parts.append(f"ignored={', '.join(ignore_patterns)}")
    if not respect_gitignore:
        filter_parts.append(".gitignore=disabled")

    filter_desc = ", ".join(filter_parts) if filter_parts else None

    print_header(summary, filter_desc)
    print_summary_cards(summary)
    print_language_distribution(summary)
    print_folder_distribution(summary)

    top_limit = parsed.top if parsed.top > 0 else None
    print_contributors_table(summary, sort_by=parsed.sort, top_n=top_limit)
    print_footer_tips(plot_requested=parsed.plot or bool(parsed.save_plot))

    if parsed.plot or parsed.save_plot:
        try:
            plot_contributions(
                summary,
                save_path=parsed.save_plot,
                show_window=parsed.plot,
                top_n=top_limit if top_limit and 1 <= top_limit <= 5 else 3
            )
        except Exception as e:
            console.print(f"[bold red]Visualization error:[/bold red] {e}")


if __name__ == "__main__":
    main()
