"""
Matplotlib visualizer for Git contribution statistics.
Mimics GitHub's contribution activity graphs with modern styling.
"""

from datetime import datetime
from typing import Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from .models import RepoSummary


def apply_github_dark_theme(fig, axes):
    """Apply GitHub Dark theme styling to matplotlib figure and axes."""
    bg_color = "#0d1117"
    card_color = "#161b22"
    border_color = "#30363d"
    text_color = "#e6edf3"
    subtext_color = "#8b949e"

    fig.patch.set_facecolor(bg_color)

    for ax in axes:
        if ax is None:
            continue
        ax.set_facecolor(card_color)
        ax.tick_params(colors=subtext_color, labelsize=9)
        ax.xaxis.label.set_color(text_color)
        ax.yaxis.label.set_color(text_color)
        ax.title.set_color(text_color)

        for spine in ax.spines.values():
            spine.set_color(border_color)
            spine.set_linewidth(1)

        ax.grid(True, linestyle="--", linewidth=0.5, color=border_color, alpha=0.7)


def plot_contributions(
    summary: RepoSummary,
    save_path: Optional[str] = None,
    show_window: bool = True,
    top_n: int = 8
) -> None:
    """
    Render a GitHub-style multi-panel visualization of repository activity and contributors.
    """
    if not summary.time_series and not summary.contributors:
        print("[!] No commit data available to visualize.")
        return

    # Create figure with 2 rows: Top = Timeline, Bottom = Contributor breakdowns
    fig = plt.figure(figsize=(13, 8), dpi=100)
    fig.canvas.manager.set_window_title(f"GitAnalyzer - {summary.repo_name} Contributions")

    # Grid layout: Row 1 = Timeline (full width), Row 2 = (Left: Ownership, Right: Commits)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1.0], hspace=0.35, wspace=0.25)
    ax_timeline = fig.add_subplot(gs[0, :])
    ax_ownership = fig.add_subplot(gs[1, 0])
    ax_commits = fig.add_subplot(gs[1, 1])

    # -------------------------------------------------------------
    # Panel 1: Activity Over Time (GitHub additions/deletions + commits)
    # -------------------------------------------------------------
    if summary.time_series:
        dates = [datetime.fromtimestamp(pt.timestamp) for pt in summary.time_series]
        additions = np.array([pt.additions for pt in summary.time_series])
        deletions = np.array([pt.deletions for pt in summary.time_series])
        commits = [pt.commits for pt in summary.time_series]

        # Convert dates to matplotlib format
        num_dates = mdates.date2num(dates)
        bar_width = max(1.0, (num_dates[-1] - num_dates[0]) / max(len(num_dates), 1) * 0.7) if len(num_dates) > 1 else 3.0

        # Green additions (+), Red deletions (-)
        ax_timeline.bar(
            dates,
            additions,
            width=bar_width,
            color="#2ea043",
            alpha=0.85,
            label="Lines Added (+)"
        )
        ax_timeline.bar(
            dates,
            -deletions,
            width=bar_width,
            color="#da3633",
            alpha=0.85,
            label="Lines Deleted (-)"
        )

        # Format timeline axes
        max_add = max(additions) if len(additions) > 0 else 0
        max_del = max(deletions) if len(deletions) > 0 else 0
        y_top = max(max_add * 1.2, 5)
        y_bot = -max(max_del * 1.2, 5) if max_del > 0 else -1
        ax_timeline.set_ylim(bottom=y_bot, top=y_top)

        # Twin axis for commit frequency line
        ax_commits_line = ax_timeline.twinx()
        ax_commits_line.plot(
            dates,
            commits,
            color="#58a6ff",
            linewidth=2.0,
            marker="o",
            markersize=4.0,
            label="Commits"
        )
        ax_commits_line.set_ylim(bottom=0, top=max(max(commits) * 1.3, 5) if commits else 5)
        ax_commits_line.set_ylabel("Commits / Week", color="#58a6ff", fontsize=10, weight="bold")
        ax_commits_line.tick_params(colors="#58a6ff", labelsize=9)
        ax_commits_line.spines["right"].set_color("#58a6ff")
        ax_commits_line.spines["top"].set_visible(False)
        ax_commits_line.spines["left"].set_visible(False)
        ax_commits_line.spines["bottom"].set_visible(False)

        # Format timeline X-axis
        ax_timeline.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax_timeline.set_ylabel("Lines Changed (+ / -)", color="#e6edf3", fontsize=10, weight="bold")
        ax_timeline.set_title(
            f"Repository Activity Over Time ({summary.repo_name})",
            fontsize=12,
            weight="bold",
            pad=10
        )
        ax_timeline.axhline(0, color="#8b949e", linewidth=0.8, linestyle="-")

        # Combine legends
        lines1, labels1 = ax_timeline.get_legend_handles_labels()
        lines2, labels2 = ax_commits_line.get_legend_handles_labels()
        ax_timeline.legend(
            lines1 + lines2,
            labels1 + labels2,
            loc="upper left",
            frameon=True,
            facecolor="#161b22",
            edgecolor="#30363d",
            labelcolor="#e6edf3",
            fontsize=9
        )
    else:
        ax_timeline.text(0.5, 0.5, "No time-series data", ha="center", va="center", color="#8b949e")

    # -------------------------------------------------------------
    # Panel 2: Current Code Ownership (Lines in latest commit)
    # -------------------------------------------------------------
    # Sort contributors by current lines
    contribs_by_lines = sorted(
        summary.contributors.values(),
        key=lambda c: c.current_lines,
        reverse=True
    )[:top_n]

    if contribs_by_lines and sum(c.current_lines for c in contribs_by_lines) > 0:
        names = [c.name[:18] + ("…" if len(c.name) > 18 else "") for c in reversed(contribs_by_lines)]
        lines = [c.current_lines for c in reversed(contribs_by_lines)]
        total_curr = max(summary.total_current_lines, 1)

        bars = ax_ownership.barh(names, lines, color="#bc8cff", alpha=0.85, height=0.6)
        ax_ownership.set_xlabel("Surviving Lines of Code", fontsize=9, weight="bold")
        ax_ownership.set_title("Current Code Ownership (HEAD)", fontsize=11, weight="bold")

        # Annotate percentages
        for bar in bars:
            val = bar.get_width()
            pct = (val / total_curr) * 100
            ax_ownership.text(
                val + (max(lines) * 0.02),
                bar.get_y() + bar.get_height() / 2,
                f"{val:,} ({pct:.1f}%)",
                va="center",
                ha="left",
                color="#e6edf3",
                fontsize=8
            )
        ax_ownership.set_xlim(0, max(lines) * 1.25 if lines else 1)
    else:
        status_msg = "Blame skipped (--no-blame)" if summary.blame_skipped else "No surviving lines tracked"
        ax_ownership.text(0.5, 0.5, status_msg, ha="center", va="center", color="#8b949e")
        ax_ownership.set_title("Current Code Ownership (HEAD)", fontsize=11, weight="bold")

    # -------------------------------------------------------------
    # Panel 3: Commits Distribution by Contributor
    # -------------------------------------------------------------
    contribs_by_commits = sorted(
        summary.contributors.values(),
        key=lambda c: c.commits,
        reverse=True
    )[:top_n]

    if contribs_by_commits:
        c_names = [c.name[:18] + ("…" if len(c.name) > 18 else "") for c in reversed(contribs_by_commits)]
        c_counts = [c.commits for c in reversed(contribs_by_commits)]
        total_c = max(summary.total_commits, 1)

        bars2 = ax_commits.barh(c_names, c_counts, color="#388bfd", alpha=0.85, height=0.6)
        ax_commits.set_xlabel("Commits Count", fontsize=9, weight="bold")
        ax_commits.set_title("Top Contributors by Commits", fontsize=11, weight="bold")

        for bar in bars2:
            val = bar.get_width()
            pct = (val / total_c) * 100
            ax_commits.text(
                val + (max(c_counts) * 0.02),
                bar.get_y() + bar.get_height() / 2,
                f"{val:,} ({pct:.1f}%)",
                va="center",
                ha="left",
                color="#e6edf3",
                fontsize=8
            )
        ax_commits.set_xlim(0, max(c_counts) * 1.25 if c_counts else 1)

    # Apply GitHub dark styling
    apply_github_dark_theme(fig, [ax_timeline, ax_ownership, ax_commits])

    # Footer note
    fig.text(
        0.5,
        0.015,
        f"Generated by GitAnalyzer • Branch: {summary.current_branch} • Total Commits: {summary.total_commits:,}",
        ha="center",
        fontsize=8,
        color="#8b949e"
    )

    if save_path:
        plt.savefig(save_path, bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
        print(f"[+] Saved contributions chart to: {save_path}")

    if show_window:
        plt.show()
    else:
        plt.close(fig)
