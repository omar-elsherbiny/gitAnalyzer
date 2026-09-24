"""
Matplotlib visualizer for Git contribution statistics.
Renders GitHub-style activity bar charts across time for the whole repository
and per top contributor.
"""

from datetime import datetime
from typing import List, Optional

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
        ax.tick_params(colors=subtext_color, labelsize=8)
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
    top_n: int = 3
) -> None:
    """
    Render GitHub-style timeline visualization:
    - Top panel: Overall repository activity over time (lines added/deleted + commits).
    - Bottom panels: Individual activity timeline bar charts for each top contributor.
    """
    if not summary.time_series or not summary.contributors:
        print("[!] No commit data available to visualize.")
        return

    # Extract dates and time series
    dates = [datetime.fromtimestamp(pt.timestamp) for pt in summary.time_series]
    num_dates = mdates.date2num(dates)
    bar_width = (
        max(1.0, (num_dates[-1] - num_dates[0]) / max(len(num_dates), 1) * 0.7)
        if len(num_dates) > 1
        else 3.0
    )

    # Sort contributors by total commits
    sorted_contribs = sorted(
        summary.contributors.values(),
        key=lambda c: c.commits,
        reverse=True
    )
    selected_contribs = sorted_contribs[:top_n]
    num_subcharts = 1 + len(selected_contribs)

    # Dynamic figure height based on number of subplots
    fig_height = max(6.0, 3.2 + (num_subcharts * 1.8))
    fig, axes = plt.subplots(
        nrows=num_subcharts,
        ncols=1,
        figsize=(13, fig_height),
        sharex=True,
        dpi=100,
        gridspec_kw={"height_ratios": [1.4] + [1.0] * len(selected_contribs), "hspace": 0.3}
    )
    if num_subcharts == 1:
        axes = [axes]

    fig.canvas.manager.set_window_title(f"GitAnalyzer - {summary.repo_name} Contributor Timelines")

    all_axes_to_theme = list(axes)

    # -------------------------------------------------------------
    # Panel 0: Overall Repository Activity Over Time
    # -------------------------------------------------------------
    ax_main = axes[0]
    additions = np.array([pt.additions for pt in summary.time_series])
    deletions = np.array([pt.deletions for pt in summary.time_series])
    commits = [pt.commits for pt in summary.time_series]

    ax_main.bar(
        dates,
        additions,
        width=bar_width,
        color="#2ea043",
        alpha=0.85,
        label="Lines Added (+)"
    )
    ax_main.bar(
        dates,
        -deletions,
        width=bar_width,
        color="#da3633",
        alpha=0.85,
        label="Lines Deleted (-)"
    )

    max_add = max(additions) if len(additions) > 0 else 0
    max_del = max(deletions) if len(deletions) > 0 else 0
    y_top = max(max_add * 1.25, 5)
    y_bot = -max(max_del * 1.25, 5) if max_del > 0 else -1
    ax_main.set_ylim(bottom=y_bot, top=y_top)
    ax_main.axhline(0, color="#8b949e", linewidth=0.8, linestyle="-")
    ax_main.set_ylabel("Lines Changed (+/-)", fontsize=9, weight="bold")
    ax_main.set_title(
        f"Overall Repository Activity Over Time • {summary.repo_name} (Branch: {summary.current_branch})",
        fontsize=11,
        weight="bold",
        pad=8
    )

    # Secondary axis for commit volume
    ax_main_commits = ax_main.twinx()
    all_axes_to_theme.append(ax_main_commits)
    ax_main_commits.plot(
        dates,
        commits,
        color="#58a6ff",
        linewidth=2.0,
        marker="o",
        markersize=4.0,
        label="Commits"
    )
    ax_main_commits.set_ylim(bottom=0, top=max(max(commits) * 1.3, 5) if commits else 5)
    ax_main_commits.set_ylabel("Commits / Week", color="#58a6ff", fontsize=9, weight="bold")
    ax_main_commits.tick_params(colors="#58a6ff", labelsize=8)
    ax_main_commits.spines["right"].set_color("#58a6ff")
    ax_main_commits.spines["top"].set_visible(False)
    ax_main_commits.spines["left"].set_visible(False)
    ax_main_commits.spines["bottom"].set_visible(False)

    # Combined legend for top plot
    lines1, labels1 = ax_main.get_legend_handles_labels()
    lines2, labels2 = ax_main_commits.get_legend_handles_labels()
    ax_main.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left",
        frameon=True,
        facecolor="#161b22",
        edgecolor="#30363d",
        labelcolor="#e6edf3",
        fontsize=8
    )

    # -------------------------------------------------------------
    # Panels 1..N: Contributor Timelines
    # -------------------------------------------------------------
    for idx, contrib in enumerate(selected_contribs, start=1):
        ax = axes[idx]
        author_key = contrib.email.lower() if contrib.email in summary.contributors else contrib.name

        c_adds = np.array([
            pt.author_additions.get(author_key, 0)
            or pt.author_additions.get(contrib.name, 0)
            for pt in summary.time_series
        ])
        c_dels = np.array([
            pt.author_deletions.get(author_key, 0)
            or pt.author_deletions.get(contrib.name, 0)
            for pt in summary.time_series
        ])
        c_commits = [
            pt.author_commits.get(author_key, 0)
            or pt.author_commits.get(contrib.name, 0)
            for pt in summary.time_series
        ]

        ax.bar(
            dates,
            c_adds,
            width=bar_width,
            color="#2ea043",
            alpha=0.85
        )
        ax.bar(
            dates,
            -c_dels,
            width=bar_width,
            color="#da3633",
            alpha=0.85
        )

        c_max_add = max(c_adds) if len(c_adds) > 0 else 0
        c_max_del = max(c_dels) if len(c_dels) > 0 else 0
        cy_top = max(c_max_add * 1.25, 4)
        cy_bot = -max(c_max_del * 1.25, 4) if c_max_del > 0 else -1
        ax.set_ylim(bottom=cy_bot, top=cy_top)
        ax.axhline(0, color="#8b949e", linewidth=0.8, linestyle="-")
        ax.set_ylabel("Lines (+/-)", fontsize=8)

        # Contributor commit line on twin axis
        ax_c_line = ax.twinx()
        all_axes_to_theme.append(ax_c_line)
        ax_c_line.plot(
            dates,
            c_commits,
            color="#58a6ff",
            linewidth=1.8,
            marker="o",
            markersize=3.5
        )
        c_max_comm = max(c_commits) if len(c_commits) > 0 else 1
        ax_c_line.set_ylim(bottom=0, top=max(c_max_comm * 1.3, 4))
        ax_c_line.set_ylabel("Commits", color="#58a6ff", fontsize=8)
        ax_c_line.tick_params(colors="#58a6ff", labelsize=8)
        ax_c_line.spines["right"].set_color("#58a6ff")
        ax_c_line.spines["top"].set_visible(False)
        ax_c_line.spines["left"].set_visible(False)
        ax_c_line.spines["bottom"].set_visible(False)

        # Title with rank, name, and total contribution summary
        email_str = f" <{contrib.email}>" if contrib.email else ""
        ax.set_title(
            f"#{idx} {contrib.name}{email_str}   •   {contrib.commits:,} commits   (+{contrib.additions:,} / -{contrib.deletions:,})",
            fontsize=9.5,
            weight="bold",
            color="#e6edf3",
            pad=6,
            loc="left"
        )

    # Format shared X-axis on the bottom subplot
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    axes[-1].set_xlabel("Timeline", fontsize=9, weight="bold", color="#e6edf3")

    # Apply GitHub Dark theme
    apply_github_dark_theme(fig, all_axes_to_theme)

    # Adjust layout cleanly without twinx warnings
    fig.subplots_adjust(top=0.94, bottom=0.08, left=0.08, right=0.92, hspace=0.38)

    if save_path:
        plt.savefig(save_path, bbox_inches="tight", facecolor=fig.get_facecolor(), dpi=150)
        print(f"[+] Saved contributions chart to: {save_path}")

    if show_window:
        plt.show()
    else:
        plt.close(fig)
