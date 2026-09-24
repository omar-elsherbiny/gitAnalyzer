# ⚡ GitAnalyzer

> A fast, polished local Git CLI tool that mirrors GitHub's Contributor Insights page for local and private repositories.

GitAnalyzer inspects any local Git repository folder and provides a breakdown of contributions, lines of code changed, surviving code ownership (via multi-threaded `git blame`), and GitHub-styled activity graphs.

---

## Features

- **Total Commits**: Accurate commit count across the repository and per contributor.
- **Contributor Distribution**: Visual percentage bars and commit counts for each contributor.
- **Lines of Code Churn (+x / -y)**: Lines added, lines deleted, and net change per contributor.
- **Current Code Ownership (HEAD)**: Surviving lines of code in the latest commit attributable to each author using parallelized `git blame`.
- **Smart Filtering**: Automatically filters out binaries and generated/vendor lockfiles (e.g. `package-lock.json`, minified JavaScript, source maps).
- **GitHub-Styled Activity Chart**: Interactive Matplotlib visualization showing weekly line changes (+/-) and commit volume over time, plus ownership rankings.
- **Flexible Sorting & Exporting**: Sort by commits, additions, deletions, lines owned, net change, or export everything to JSON.

---

## Installation

GitAnalyzer only requires Python 3.8+ and standard dependencies (`rich`, `matplotlib`).

```bash
pip install -e .
```

After installation, the `gitanalyzer` command will be globally available in your terminal. You can also run it directly without installing via:

```bash
python analyzer.py [repo_path] [options]
```

---

## Quick Usage Examples

### 1. Basic Analysis (Current Directory)
```bash
gitanalyzer
# or: python analyzer.py
```

### 2. Analyze a Specific Repository Path
```bash
gitanalyzer C:/path/to/my-repo
```

### 3. Open Interactive GitHub-Style Chart
```bash
gitanalyzer . -p
# or: gitanalyzer . --plot
```

### 4. Export Chart to Image Without Opening Window
```bash
gitanalyzer . --save-plot contributions.png
```

### 5. Sort by Current Surviving Code Lines (Ownership)
```bash
gitanalyzer . --sort lines
```

### 6. Filter by Date Range or Branch
```bash
gitanalyzer . --since "2024-01-01" --until "2024-12-31" -b main
```

### 7. Instant Blameless Mode (Fast on Huge Monorepos)
```bash
gitanalyzer . --no-blame
```

### 8. Machine-Readable JSON Output
```bash
gitanalyzer . --json
```

---

## CLI Options & Flags

| Flag | Short | Description |
|------|-------|-------------|
| `repo_path` | | Path to the Git repository (default: `.`) |
| `--branch` | `-b` | Specific branch or commit ref to analyze (default: HEAD) |
| `--since` | `-s` | Include commits after date or git revision (e.g. `2024-01-01`) |
| `--until` | `-u` | Include commits before date or git revision |
| `--plot` | `-p` | Open interactive Matplotlib contribution chart window |
| `--save-plot PATH` | | Export chart to an image file (PNG, SVG, PDF) |
| `--sort METRIC` | | Sort table by: `commits`, `additions`, `deletions`, `lines`, `net`, `churn` |
| `--top N` | | Limit contributor table to top N authors (default: 20) |
| `--by-email` | | Group contributors by email instead of author name |
| `--no-blame` | | Skip blame line ownership analysis for instant speed |
| `--all-files` | | Disable smart filtering and blame all tracked files |
| `--ext .py .js` | `-e` | Only calculate line ownership for specified file extensions |
| `--workers N` | `-w` | Number of worker threads for parallel blame (default: 16) |
| `--json` | | Output report as structured JSON |
| `--help` | `-h` | Show help message and exit |
