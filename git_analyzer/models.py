"""
Data models for Git repository statistics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class ContributorStats:
    name: str
    email: str = ""
    commits: int = 0
    additions: int = 0
    deletions: int = 0
    current_lines: int = 0  # Surviving lines in latest commit (via blame)
    first_commit_date: Optional[datetime] = None
    last_commit_date: Optional[datetime] = None

    @property
    def net_lines(self) -> int:
        return self.additions - self.deletions

    @property
    def churn(self) -> int:
        return self.additions + self.deletions


@dataclass
class TimeBucketStats:
    period_label: str  # e.g., "2024-W12" or "2024-03"
    timestamp: float   # epoch timestamp for sorting/plotting
    commits: int = 0
    additions: int = 0
    deletions: int = 0
    author_commits: Dict[str, int] = field(default_factory=dict)


@dataclass
class RepoSummary:
    repo_path: str
    repo_name: str
    current_branch: str
    head_hash: str = ""
    head_message: str = ""
    head_author: str = ""
    head_date: Optional[datetime] = None
    
    total_commits: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    total_current_lines: int = 0
    
    first_commit_date: Optional[datetime] = None
    last_commit_date: Optional[datetime] = None
    
    contributors: Dict[str, ContributorStats] = field(default_factory=dict)
    time_series: List[TimeBucketStats] = field(default_factory=list)
    
    blame_skipped: bool = False
    blamed_files_count: int = 0
    total_files_count: int = 0

    @property
    def total_net_lines(self) -> int:
        return self.total_additions - self.total_deletions
