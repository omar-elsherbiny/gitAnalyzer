"""
Unit and integration tests for GitAnalyzer.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from git_analyzer.git_engine import (
    analyze_repository,
    check_git_installed,
    compute_blame_stats,
    is_git_repo,
    is_smart_eligible_file,
    parse_commit_history,
)
from git_analyzer.models import ContributorStats, RepoSummary
from git_analyzer.visualizer import plot_contributions


class TestGitAnalyzer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = os.path.join(self.temp_dir, "test_repo")
        os.makedirs(self.repo_dir, exist_ok=True)

        # Helper to run git commands in test repo
        self._run_git(["init"])
        self._run_git(["config", "user.name", "Initial Author"])
        self._run_git(["config", "user.email", "initial@example.com"])

    def tearDown(self):
        # Clean up temp dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_git(self, args):
        cmd = ["git", "-C", self.repo_dir] + args
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            raise RuntimeError(f"Git command failed: {' '.join(cmd)}\nError: {res.stderr}")
        return res

    def _create_and_commit(self, filename, content, author_name, author_email, msg):
        self._run_git(["config", "user.name", author_name])
        self._run_git(["config", "user.email", author_email])
        filepath = os.path.join(self.repo_dir, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        self._run_git(["add", filename])
        self._run_git(["commit", "-m", msg])

    def test_git_installed_and_is_repo(self):
        self.assertTrue(check_git_installed())
        self.assertTrue(is_git_repo(self.repo_dir))
        self.assertFalse(is_git_repo(self.temp_dir))

    def test_smart_eligible_file(self):
        # Code files should be eligible
        self.assertTrue(is_smart_eligible_file("main.py"))
        self.assertTrue(is_smart_eligible_file("src/utils.js"))
        self.assertTrue(is_smart_eligible_file("README.md"))

        # Binaries should be excluded in smart mode
        self.assertFalse(is_smart_eligible_file("logo.png"))
        self.assertFalse(is_smart_eligible_file("archive.zip"))

        # Lockfiles should be excluded in smart mode
        self.assertFalse(is_smart_eligible_file("package-lock.json"))
        self.assertFalse(is_smart_eligible_file("yarn.lock"))
        self.assertFalse(is_smart_eligible_file("Cargo.lock"))

        # Minified files should be excluded in smart mode
        self.assertFalse(is_smart_eligible_file("bundle.min.js"))

        # When smart mode is off, everything is eligible
        self.assertTrue(is_smart_eligible_file("package-lock.json", smart_filter=False))

    def test_commit_history_and_ownership(self):
        # Alice creates a file with 4 lines
        self._create_and_commit(
            "app.py",
            "line 1\nline 2\nline 3\nline 4\n",
            "Alice Smith",
            "alice@test.com",
            "Initial commit by Alice"
        )

        # Bob adds 3 lines and modifies 1 line
        self._create_and_commit(
            "app.py",
            "line 1\nline 2 (edited by Bob)\nline 3\nline 4\nline 5\nline 6\nline 7\n",
            "Bob Jones",
            "bob@test.com",
            "Update app.py by Bob"
        )

        # Charlie adds a new helper file with 2 lines
        self._create_and_commit(
            "helper.py",
            "def foo():\n    return 42\n",
            "Charlie Brown",
            "charlie@test.com",
            "Add helper by Charlie"
        )

        # Analyze the repo
        summary = analyze_repository(self.repo_dir)

        # Total commits: 3
        self.assertEqual(summary.total_commits, 3)
        self.assertEqual(len(summary.contributors), 3)

        # Verify Alice stats
        alice = summary.contributors["Alice Smith"]
        self.assertEqual(alice.commits, 1)
        self.assertEqual(alice.additions, 4)
        self.assertEqual(alice.deletions, 0)
        # Alice has lines 1, 3, 4 remaining (3 lines surviving)
        self.assertEqual(alice.current_lines, 3)

        # Verify Bob stats
        bob = summary.contributors["Bob Jones"]
        self.assertEqual(bob.commits, 1)
        # Bob modified 1 line (1 del + 1 add) + added 3 lines = 4 additions, 1 deletion
        self.assertEqual(bob.additions, 4)
        self.assertEqual(bob.deletions, 1)
        # Bob owns line 2, 5, 6, 7 (4 lines surviving)
        self.assertEqual(bob.current_lines, 4)

        # Verify Charlie stats
        charlie = summary.contributors["Charlie Brown"]
        self.assertEqual(charlie.commits, 1)
        self.assertEqual(charlie.additions, 2)
        self.assertEqual(charlie.deletions, 0)
        self.assertEqual(charlie.current_lines, 2)

        # Total current lines in repo at HEAD: 3 (Alice) + 4 (Bob) + 2 (Charlie) = 9 lines
        self.assertEqual(summary.total_current_lines, 9)

    def test_save_plot(self):
        self._create_and_commit("index.js", "console.log('hi');\n", "Dev One", "dev1@test.com", "init")
        summary = analyze_repository(self.repo_dir)

        plot_path = os.path.join(self.temp_dir, "test_chart.png")
        plot_contributions(summary, save_path=plot_path, show_window=False)

        self.assertTrue(os.path.exists(plot_path))
        self.assertGreater(os.path.getsize(plot_path), 1000)

    def test_empty_repo(self):
        empty_dir = os.path.join(self.temp_dir, "empty_repo")
        os.makedirs(empty_dir, exist_ok=True)
        subprocess.run(["git", "-C", empty_dir, "init"], capture_output=True)

        summary = analyze_repository(empty_dir)
        self.assertEqual(summary.total_commits, 0)
        self.assertEqual(len(summary.contributors), 0)


    def test_gitignore_exclusion(self):
        # Create .gitignore ignoring *.log and temp/
        with open(os.path.join(self.repo_dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("*.log\ntemp/\n")
        self._run_git(["add", ".gitignore"])
        self._run_git(["commit", "-m", "Add .gitignore"])

        # Force add a log file and a temp file (as sometimes happens in git history)
        log_path = os.path.join(self.repo_dir, "debug.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("line 1\nline 2\n")
        self._run_git(["add", "-f", "debug.log"])
        self._run_git(["commit", "-m", "Commit log file"])

        # Add a normal code file
        self._create_and_commit("service.py", "def run():\n    pass\n", "Alice", "alice@test.com", "Add service")

        # When gitignore is respected (default), debug.log should be excluded from churn and blame
        summary_default = analyze_repository(self.repo_dir, respect_gitignore=True)
        # debug.log has 2 lines, service.py has 2 lines, .gitignore has 2 lines
        # alice added service.py (2 lines)
        alice = summary_default.contributors["Alice"]
        self.assertEqual(alice.current_lines, 2)
        # Total current lines should not include debug.log (2 lines for .gitignore + 2 for service.py = 4)
        self.assertEqual(summary_default.total_current_lines, 4)

        # When gitignore is disabled (--no-gitignore), debug.log should be included (2 + 2 + 2 = 6)
        summary_no_gitignore = analyze_repository(self.repo_dir, respect_gitignore=False)
        self.assertEqual(summary_no_gitignore.total_current_lines, 6)

    def test_custom_ignore_patterns(self):
        self._create_and_commit("main.py", "x = 1\n", "DevA", "deva@test.com", "commit code")
        self._create_and_commit("tests/test_main.py", "assert True\n", "DevA", "deva@test.com", "commit tests")
        self._create_and_commit("docs/readme.txt", "doc text\n", "DevB", "devb@test.com", "commit docs")

        # Without ignore, both DevA (2 commits) and DevB (1 commit) exist
        summary_all = analyze_repository(self.repo_dir)
        self.assertIn("DevB", summary_all.contributors)
        self.assertEqual(summary_all.contributors["DevA"].commits, 2)

        # Ignore tests and docs
        summary_filtered = analyze_repository(
            self.repo_dir,
            custom_ignore_patterns=["tests/*", "docs/*"]
        )
        # DevB only committed docs, so DevB should not appear in filtered commits
        self.assertNotIn("DevB", summary_filtered.contributors)
        # DevA's test commit was skipped, leaving 1 code commit
        self.assertEqual(summary_filtered.contributors["DevA"].commits, 1)
        self.assertEqual(summary_filtered.contributors["DevA"].current_lines, 1)


if __name__ == "__main__":
    unittest.main()

