#!/usr/bin/env python3
"""
GitAnalyzer - Local Git Contributions & Code Ownership CLI Tool.
Run with: python analyzer.py [repo_path] [options]
"""

import sys

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from git_analyzer.cli import main

if __name__ == "__main__":
    main(sys.argv[1:])
