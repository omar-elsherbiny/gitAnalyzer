"""
Terminal UI formatting and reporting using Rich.
Provides GitHub-inspired CLI tables, summary cards, language distribution bars,
and VSCodeCounter-style folder code breakdowns.
"""

from datetime import datetime
from typing import List, Optional

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import ContributorStats, FolderStats, LanguageStats, RepoSummary

console = Console()


def format_number(n: int) -> str:
    """Format integer with thousands separator."""
    return f"{n:,}"


def render_mini_bar(ratio: float, width: int = 10, fill_char: str = "█", empty_char: str = "░") -> str:
    """Render a compact horizontal bar string based on a ratio between 0.0 and 1.0."""
    ratio = max(0.0, min(1.0, ratio))
    filled_len = int(round(ratio * width))
    empty_len = width - filled_len
    return f"{fill_char * filled_len}{empty_char * empty_len}"


def print_header(summary: RepoSummary, filter_desc: Optional[str] = None):
    """Print top-level repository header panel."""
    head_info = f"[cyan]{summary.head_hash}[/cyan]" if summary.head_hash else "None"
    if summary.head_message:
        msg = summary.head_message[:60] + ("..." if len(summary.head_message) > 60 else "")
        head_info += f" - [white]{msg}[/white]"

    date_range_str = "All time"
    if summary.first_commit_date and summary.last_commit_date:
        d1 = summary.first_commit_date.strftime("%Y-%m-%d")
        d2 = summary.last_commit_date.strftime("%Y-%m-%d")
        date_range_str = f"{d1} to {d2}"

    blame_status = (
        f"[yellow]Skipped (--no-blame)[/yellow]"
        if summary.blame_skipped
        else f"[green]{summary.blamed_files_count}[/green] / {summary.total_files_count} files"
    )

    content = f"""[bold white]Repository:[/bold white] [bold cyan]{summary.repo_name}[/bold cyan] ([dim]{summary.repo_path}[/dim])
[bold white]Branch/Ref:[/bold white] [green]{summary.current_branch}[/green]   |   [bold white]Latest Commit:[/bold white] {head_info}
[bold white]Date Span:[/bold white]  {date_range_str}   |   [bold white]Analyzed Files:[/bold white] {blame_status}"""

    if filter_desc:
        content += f"\n[bold yellow]Filters Applied:[/bold yellow] {filter_desc}"

    panel = Panel(
        content,
        title="[bold magenta]⚡ GitAnalyzer • Repository Overview[/bold magenta]",
        border_style="cyan",
        padding=(1, 2)
    )
    console.print(panel)


def print_summary_cards(summary: RepoSummary):
    """Print high-level statistics cards."""
    table = Table.grid(expand=True, padding=(0, 2))
    table.add_column(justify="center", ratio=1)
    table.add_column(justify="center", ratio=1)
    table.add_column(justify="center", ratio=1)
    table.add_column(justify="center", ratio=1)

    p1 = Panel(
        f"[bold cyan]{format_number(summary.total_commits)}[/bold cyan]\n[dim]across {len(summary.contributors)} contributors[/dim]",
        title="[bold]Total Commits[/bold]",
        border_style="blue",
        padding=(0, 1)
    )

    net_color = "green" if summary.total_net_lines >= 0 else "red"
    net_sign = "+" if summary.total_net_lines >= 0 else ""
    p2 = Panel(
        f"[green]+{format_number(summary.total_additions)}[/green]  /  [red]-{format_number(summary.total_deletions)}[/red]\n[dim]Net: [{net_color}]{net_sign}{format_number(summary.total_net_lines)}[/{net_color}][/dim]",
        title="[bold]Lines Changed[/bold]",
        border_style="green",
        padding=(0, 1)
    )

    p3 = Panel(
        f"[bold magenta]{format_number(summary.total_current_lines)}[/bold magenta]\n[dim]lines in tracked code[/dim]",
        title="[bold]Total Lines of Code[/bold]",
        border_style="magenta",
        padding=(0, 1)
    )

    if summary.contributors:
        top_committer = max(summary.contributors.values(), key=lambda c: c.commits)
        p4_content = f"[bold white]{top_committer.name[:16]}[/bold white]\n[dim]{format_number(top_committer.commits)} commits[/dim]"
    else:
        p4_content = "[dim]None[/dim]"

    p4 = Panel(
        p4_content,
        title="[bold]Top Contributor[/bold]",
        border_style="yellow",
        padding=(0, 1)
    )

    table.add_row(p1, p2, p3, p4)
    console.print(table)
    console.print()


def print_language_distribution(summary: RepoSummary, bar_width: int = 55):
    """
    Render GitHub-style continuous language distribution bar with exact colors and percentages.
    """
    if not summary.language_stats or summary.total_current_lines == 0:
        return

    total_lines = summary.total_current_lines
    bar_text = Text()
    legend_items = []

    top_languages = []
    other_lines = 0

    for lang in summary.language_stats:
        pct = (lang.lines / total_lines) * 100
        if pct >= 1.2 or len(top_languages) < 5:
            top_languages.append((lang, pct))
        else:
            other_lines += lang.lines

    if other_lines > 0:
        other_pct = (other_lines / total_lines) * 100
        top_languages.append((LanguageStats(name="Other", color="#8b949e", lines=other_lines), other_pct))

    allocated_width = 0
    num_langs = len(top_languages)
    for idx, (lang, pct) in enumerate(top_languages):
        if idx == num_langs - 1:
            seg_len = max(1, bar_width - allocated_width)
        else:
            seg_len = max(1, int(round((pct / 100.0) * bar_width)))
            if allocated_width + seg_len > bar_width:
                seg_len = max(1, bar_width - allocated_width)
        allocated_width += seg_len
        bar_text.append("█" * seg_len, style=lang.color)

        legend_items.append(
            f"[{lang.color}]●[/{lang.color}] [bold white]{lang.name}[/bold white] [dim]{pct:4.1f}%[/dim]"
        )

    console.print("[bold cyan]💻 Languages[/bold cyan]")
    console.print(bar_text)
    console.print("   ".join(legend_items))
    console.print()


def print_folder_distribution(summary: RepoSummary, max_folders: int = 6):
    """
    Render VSCodeCounter-style brief table showing the biggest folders and their lines of code.
    """
    if not summary.folder_stats or summary.total_current_lines == 0:
        return

    table = Table(
        title="[bold cyan]📂 Code Volume by Folder[/bold cyan]",
        header_style="bold white on #161b22",
        border_style="#30363d",
        show_lines=False,
        expand=True
    )

    table.add_column("Folder", justify="left", style="white", ratio=3)
    table.add_column("Files", justify="right", style="cyan", ratio=1)
    table.add_column("Lines of Code", justify="right", style="magenta", ratio=2)
    table.add_column("Share", justify="right", ratio=2)

    total_lines = summary.total_current_lines
    displayed = summary.folder_stats[:max_folders]
    other_lines = sum(f.lines for f in summary.folder_stats[max_folders:])
    other_files = sum(f.files_count for f in summary.folder_stats[max_folders:])

    for f in displayed:
        pct = (f.lines / total_lines) * 100 if total_lines > 0 else 0.0
        bar = render_mini_bar(f.lines / total_lines if total_lines > 0 else 0.0, width=8)
        table.add_row(
            f"[bold]{f.folder_path}[/bold]",
            format_number(f.files_count),
            format_number(f.lines),
            f"{pct:4.1f}% [cyan]{bar}[/cyan]"
        )

    if other_lines > 0:
        other_pct = (other_lines / total_lines) * 100
        other_bar = render_mini_bar(other_lines / total_lines, width=8)
        table.add_row(
            f"[dim]Other ({len(summary.folder_stats) - max_folders} folders)[/dim]",
            format_number(other_files),
            format_number(other_lines),
            f"[dim]{other_pct:4.1f}%[/dim] [dim]{other_bar}[/dim]"
        )

    console.print(table)
    console.print()


def print_contributors_table(
    summary: RepoSummary,
    sort_by: str = "commits",
    top_n: Optional[int] = None
):
    """
    Render table of contributors showing commits distribution,
    lines added/deleted, net change, and current line ownership.
    """
    if not summary.contributors:
        console.print("[yellow]No contributors found for the specified filters.[/yellow]")
        return

    sort_keys = {
        "commits": lambda c: c.commits,
        "additions": lambda c: c.additions,
        "deletions": lambda c: c.deletions,
        "net": lambda c: c.net_lines,
        "lines": lambda c: c.current_lines,
        "churn": lambda c: c.churn,
    }
    key_func = sort_keys.get(sort_by, lambda c: c.commits)
    sorted_contribs = sorted(summary.contributors.values(), key=key_func, reverse=True)

    total_contributors = len(sorted_contribs)
    displayed_contribs = sorted_contribs[:top_n] if top_n else sorted_contribs

    table = Table(
        title="[bold cyan]👤 Contributor Breakdown & Code Ownership[/bold cyan]",
        header_style="bold white on #161b22",
        border_style="#30363d",
        show_lines=False,
        expand=True
    )

    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Contributor", justify="left", style="white", ratio=2)
    table.add_column("Commits", justify="right", style="cyan", ratio=2)
    table.add_column("Additions (+)", justify="right", style="green", ratio=1)
    table.add_column("Deletions (-)", justify="right", style="red", ratio=1)
    table.add_column("Net", justify="right", ratio=1)
    table.add_column("Current Lines (HEAD)", justify="right", style="magenta", ratio=2)
    table.add_column("Active Period", justify="center", style="dim", ratio=1)

    total_c = max(1, summary.total_commits)
    total_l = max(1, summary.total_current_lines)

    for idx, c in enumerate(displayed_contribs, start=1):
        c_pct = (c.commits / total_c) * 100
        c_bar = render_mini_bar(c.commits / total_c, width=8)
        commits_cell = f"{format_number(c.commits)} [dim]({c_pct:4.1f}%)[/dim] [blue]{c_bar}[/blue]"

        adds_cell = f"+{format_number(c.additions)}"
        dels_cell = f"-{format_number(c.deletions)}"

        net_val = c.net_lines
        net_sign = "+" if net_val >= 0 else ""
        net_color = "green" if net_val >= 0 else "red"
        net_cell = f"[{net_color}]{net_sign}{format_number(net_val)}[/{net_color}]"

        if summary.blame_skipped:
            curr_lines_cell = "[dim]N/A[/dim]"
        else:
            l_pct = (c.current_lines / total_l) * 100 if summary.total_current_lines > 0 else 0.0
            l_bar = render_mini_bar((c.current_lines / total_l) if summary.total_current_lines > 0 else 0.0, width=8)
            curr_lines_cell = f"{format_number(c.current_lines)} [dim]({l_pct:4.1f}%)[/dim] [magenta]{l_bar}[/magenta]"

        name_cell = f"[bold]{c.name}[/bold]"
        if c.email:
            name_cell += f"\n[dim]{c.email}[/dim]"

        if c.first_commit_date and c.last_commit_date:
            span = f"{c.first_commit_date.strftime('%Y/%m')} - {c.last_commit_date.strftime('%Y/%m')}"
        else:
            span = "-"

        table.add_row(
            str(idx),
            name_cell,
            commits_cell,
            adds_cell,
            dels_cell,
            net_cell,
            curr_lines_cell,
            span
        )

    console.print(table)

    if top_n and total_contributors > top_n:
        console.print(
            f"[dim]Showing top {top_n} of {total_contributors} contributors (sorted by {sort_by}). Use --top to show more.[/dim]\n"
        )
    else:
        console.print()


def print_footer_tips(plot_requested: bool):
    """Print tips on CLI flags."""
    tips = []
    if not plot_requested:
        tips.append("Pass [bold green]--plot[/bold green] (or [bold green]-p[/bold green]) to view the graphical contributions chart.")
        tips.append("Pass [bold cyan]--save-plot <file.png>[/bold cyan] to export chart without opening a window.")

    tips.append("Use [bold]--sort <commits|additions|deletions|lines|net>[/bold] to reorder the contributor table.")
    tips.append("Use [bold]-i 'tests/*' 'docs/*'[/bold] to skip files or directories from analysis.")
    tips.append("Use [bold]--no-blame[/bold] for instant analysis on massive codebases.")

    tip_text = "\n".join(f"• {t}" for t in tips)
    console.print(Panel(tip_text, title="[dim]Tips & Options[/dim]", border_style="dim", padding=(0, 1)))
