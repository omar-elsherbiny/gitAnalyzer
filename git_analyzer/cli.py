"""
CLI interface and execution entrypoint for GitAnalyzer.
"""

import argparse
from datetime import datetime
import json
import os
import sys
from typing import Any, Dict

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
    print_footer_tips,
    print_header,
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
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="gitanalyzer",
        description="⚡ Local Git Repository Insights & Contributions Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gitanalyzer                           # Analyze current directory
  gitanalyzer C:/path/to/my-repo         # Analyze specified git repo
  gitanalyzer . -p                      # Analyze and display matplotlib activity chart
  gitanalyzer . --save-plot chart.png   # Save chart to an image file
  gitanalyzer . --since "2024-01-01"     # Filter commits since Jan 1, 2024
  gitanalyzer . --sort lines            # Sort contributors by surviving code lines
  gitanalyzer . --no-blame              # Fast analysis skipping git blame
  gitanalyzer . --json                  # Output summary as JSON
        """
    )

    parser.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to git repository directory (default: current directory)"
    )

    parser.add_argument(
        "-b", "--branch",
        default=None,
        help="Target branch or commit ref to analyze (default: current branch / HEAD)"
    )

    parser.add_argument(
        "-s", "--since",
        default=None,
        help="Filter commits since date or ref (e.g., '2024-01-01', '1 month ago')"
    )

    parser.add_argument(
        "-u", "--until",
        default=None,
        help="Filter commits until date or ref (e.g., '2024-12-31')"
    )

    parser.add_argument(
        "-p", "--plot",
        action="store_true",
        help="Open interactive Matplotlib contribution & activity graph window"
    )

    parser.add_argument(
        "--save-plot",
        metavar="FILEPATH",
        default=None,
        help="Export Matplotlib contribution graph to image file (e.g., contributions.png)"
    )

    parser.add_argument(
        "--no-blame",
        action="store_true",
        help="Skip calculating current surviving lines (blame) for faster execution"
    )

    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Blame all tracked files (disables smart exclusion of lockfiles and minified code)"
    )

    parser.add_argument(
        "-e", "--ext",
        nargs="+",
        default=None,
        help="Filter blame to specific file extensions (e.g., -e .py .js .ts)"
    )

    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of top contributors to display in table (default: 20, 0 for all)"
    )

    parser.add_argument(
        "--sort",
        choices=["commits", "additions", "deletions", "lines", "net", "churn"],
        default="commits",
        help="Metric to sort contributor table by (default: commits)"
    )

    parser.add_argument(
        "--by-email",
        action="store_true",
        help="Group and identify contributors by author email instead of name"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Number of parallel worker threads for git blame (default: 16)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )

    return parser.parse_args(args)


def main(args=None):
    parsed = parse_args(args)

    allowed_exts = None
    if parsed.ext:
        allowed_exts = {e if e.startswith(".") else f".{e}" for e in parsed.ext}

    # Progress bar setup for blame
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
                blame_progress_callback=None
            )

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    # JSON output mode
    if parsed.json:
        data = repo_summary_to_dict(summary)
        print(json.dumps(data, indent=2))
        return

    # Rich Terminal Output mode
    filter_parts = []
    if parsed.branch:
        filter_parts.append(f"branch={parsed.branch}")
    if parsed.since:
        filter_parts.append(f"since={parsed.since}")
    if parsed.until:
        filter_parts.append(f"until={parsed.until}")
    if allowed_exts:
        filter_parts.append(f"extensions={', '.join(sorted(allowed_exts))}")
    filter_desc = ", ".join(filter_parts) if filter_parts else None

    print_header(summary, filter_desc)
    print_summary_cards(summary)
    
    top_limit = parsed.top if parsed.top > 0 else None
    print_contributors_table(summary, sort_by=parsed.sort, top_n=top_limit)
    print_footer_tips(plot_requested=parsed.plot or bool(parsed.save_plot))

    # Matplotlib Graph handling
    if parsed.plot or parsed.save_plot:
        try:
            plot_contributions(
                summary,
                save_path=parsed.save_plot,
                show_window=parsed.plot,
                top_n=top_limit if top_limit and top_limit < 10 else 8
            )
        except Exception as e:
            console.print(f"[bold red]Visualization error:[/bold red] {e}")


if __name__ == "__main__":
    main()
