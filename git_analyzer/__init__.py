"""
GitAnalyzer package.
"""

from .git_engine import analyze_repository
from .models import ContributorStats, RepoSummary
from .visualizer import plot_contributions

__all__ = [
    "analyze_repository",
    "ContributorStats",
    "RepoSummary",
    "plot_contributions",
]
