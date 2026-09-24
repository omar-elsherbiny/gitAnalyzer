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

        self._run_git(["init"])
        self._run_git(["config", "user.name", "Initial Author"])
        self._run_git(["config", "user.email", "initial@example.com"])

    def tearDown(self):
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
        self.assertTrue(is_smart_eligible_file("main.py"))
        self.assertTrue(is_smart_eligible_file("src/utils.js"))
        self.assertTrue(is_smart_eligible_file("README.md"))

        self.assertFalse(is_smart_eligible_file("logo.png"))
        self.assertFalse(is_smart_eligible_file("archive.zip"))

        self.assertFalse(is_smart_eligible_file("package-lock.json"))
        self.assertFalse(is_smart_eligible_file("yarn.lock"))
        self.assertFalse(is_smart_eligible_file("Cargo.lock"))

        self.assertFalse(is_smart_eligible_file("bundle.min.js"))
        self.assertTrue(is_smart_eligible_file("package-lock.json", smart_filter=False))

    def test_commit_history_and_ownership(self):
        self._create_and_commit(
            "app.py",
            "line 1\nline 2\nline 3\nline 4\n",
            "Alice Smith",
            "alice@test.com",
            "Initial commit by Alice"
        )

        self._create_and_commit(
            "app.py",
            "line 1\nline 2 (edited by Bob)\nline 3\nline 4\nline 5\nline 6\nline 7\n",
            "Bob Jones",
            "bob@test.com",
            "Update app.py by Bob"
        )

        self._create_and_commit(
            "helper.py",
            "def foo():\n    return 42\n",
            "Charlie Brown",
            "charlie@test.com",
            "Add helper by Charlie"
        )

        summary = analyze_repository(self.repo_dir)

        self.assertEqual(summary.total_commits, 3)
        self.assertEqual(len(summary.contributors), 3)

        alice = summary.contributors["Alice Smith"]
        self.assertEqual(alice.commits, 1)
        self.assertEqual(alice.additions, 4)
        self.assertEqual(alice.deletions, 0)
        self.assertEqual(alice.current_lines, 3)

        bob = summary.contributors["Bob Jones"]
        self.assertEqual(bob.commits, 1)
        self.assertEqual(bob.additions, 4)
        self.assertEqual(bob.deletions, 1)
        self.assertEqual(bob.current_lines, 4)

        charlie = summary.contributors["Charlie Brown"]
        self.assertEqual(charlie.commits, 1)
        self.assertEqual(charlie.additions, 2)
        self.assertEqual(charlie.deletions, 0)
        self.assertEqual(charlie.current_lines, 2)

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
        with open(os.path.join(self.repo_dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("*.log\ntemp/\n")
        self._run_git(["add", ".gitignore"])
        self._run_git(["commit", "-m", "Add .gitignore"])

        log_path = os.path.join(self.repo_dir, "debug.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("line 1\nline 2\n")
        self._run_git(["add", "-f", "debug.log"])
        self._run_git(["commit", "-m", "Commit log file"])

        self._create_and_commit("service.py", "def run():\n    pass\n", "Alice", "alice@test.com", "Add service")

        summary_default = analyze_repository(self.repo_dir, respect_gitignore=True)
        alice = summary_default.contributors["Alice"]
        self.assertEqual(alice.current_lines, 2)
        self.assertEqual(summary_default.total_current_lines, 4)

        summary_no_gitignore = analyze_repository(self.repo_dir, respect_gitignore=False)
        self.assertEqual(summary_no_gitignore.total_current_lines, 6)

    def test_custom_ignore_patterns(self):
        self._create_and_commit("main.py", "x = 1\n", "DevA", "deva@test.com", "commit code")
        self._create_and_commit("tests/test_main.py", "assert True\n", "DevA", "deva@test.com", "commit tests")
        self._create_and_commit("docs/readme.txt", "doc text\n", "DevB", "devb@test.com", "commit docs")

        summary_all = analyze_repository(self.repo_dir)
        self.assertIn("DevB", summary_all.contributors)
        self.assertEqual(summary_all.contributors["DevA"].commits, 2)

        summary_filtered = analyze_repository(
            self.repo_dir,
            custom_ignore_patterns=["tests/*", "docs/*"]
        )
        self.assertNotIn("DevB", summary_filtered.contributors)
        self.assertEqual(summary_filtered.contributors["DevA"].commits, 1)
        self.assertEqual(summary_filtered.contributors["DevA"].current_lines, 1)


if __name__ == "__main__":
    unittest.main()
