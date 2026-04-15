"""
deployer.py — Push any local folder to a new GitHub repo and enable GitHub Pages.
Uses gh CLI + git. No API key, no third-party services.
Free hosting at: https://akilalohanchannels-create.github.io/<repo-name>
"""

import subprocess
import time
from pathlib import Path

GITHUB_OWNER = "akilalohanchannels-create"


def _run(cmd: list, cwd: str = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def _repo_exists(repo_name: str) -> bool:
    result = _run(
        ["gh", "repo", "view", f"{GITHUB_OWNER}/{repo_name}"],
        check=False,
    )
    return result.returncode == 0


def _write_github_actions_workflow(site_dir: Path):
    """Add a GitHub Actions workflow so every push auto-deploys to Pages."""
    workflows_dir = site_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflow = workflows_dir / "deploy.yml"
    workflow.write_text(
        """name: Deploy to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v4
      - uses: actions/upload-pages-artifact@v3
        with:
          path: '.'
      - uses: actions/deploy-pages@v4
        id: deployment
""",
        encoding="utf-8",
    )


def deploy_site(
    site_dir: str,
    repo_name: str = None,
    custom_domain: str = None,
    commit_message: str = "Deploy website",
) -> dict:
    """
    Deploy a local folder to GitHub Pages.

    Args:
        site_dir:      Local folder containing the website files
        repo_name:     GitHub repo name (default: folder name)
        custom_domain: Optional custom domain e.g. "mysite.com"
        commit_message: Git commit message

    Returns:
        dict with repo_url and live_url
    """
    site_path = Path(site_dir).resolve()

    if not site_path.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    # Default repo name from folder name
    if not repo_name:
        repo_name = site_path.name.lower().replace(" ", "-").replace("_", "-")

    print(f"[Deployer] Deploying {site_path.name} → github.com/{GITHUB_OWNER}/{repo_name}")

    # Add GitHub Actions workflow for auto-deploy
    _write_github_actions_workflow(site_path)

    # Add CNAME file if custom domain provided
    if custom_domain:
        cname_path = site_path / "CNAME"
        cname_path.write_text(custom_domain.strip(), encoding="utf-8")
        print(f"[Deployer] CNAME set to {custom_domain}")

    # Initialize git if needed
    git_dir = site_path / ".git"
    if not git_dir.exists():
        _run(["git", "init", "-b", "main"], cwd=str(site_path))
        print("[Deployer] Git initialized")

    # Configure git identity if not set
    _run(["git", "config", "user.email", "deploy@website-cloner"], cwd=str(site_path), check=False)
    _run(["git", "config", "user.name", "Website Cloner"], cwd=str(site_path), check=False)

    # Create GitHub repo if it doesn't exist
    if not _repo_exists(repo_name):
        print(f"[Deployer] Creating repo {GITHUB_OWNER}/{repo_name}...")
        _run([
            "gh", "repo", "create", repo_name,
            "--public",
            "--source", str(site_path),
            "--remote", "origin",
        ])
    else:
        # Repo exists — make sure remote is set
        print(f"[Deployer] Repo already exists, pushing to existing...")
        remotes = _run(["git", "remote"], cwd=str(site_path), check=False)
        if "origin" not in remotes.stdout:
            _run([
                "git", "remote", "add", "origin",
                f"https://github.com/{GITHUB_OWNER}/{repo_name}.git"
            ], cwd=str(site_path))

    # Stage, commit, push
    _run(["git", "add", "-A"], cwd=str(site_path))

    # Check if there's anything to commit
    status = _run(["git", "status", "--porcelain"], cwd=str(site_path))
    if status.stdout.strip():
        _run(["git", "commit", "-m", commit_message], cwd=str(site_path))

    _run(["git", "push", "-u", "origin", "main", "--force"], cwd=str(site_path))
    print("[Deployer] Pushed to GitHub ✓")

    # Enable GitHub Pages via API
    print("[Deployer] Enabling GitHub Pages...")
    pages_result = _run([
        "gh", "api",
        f"repos/{GITHUB_OWNER}/{repo_name}/pages",
        "--method", "POST",
        "-f", "build_type=workflow",
    ], check=False)

    if pages_result.returncode != 0:
        # Pages might already be enabled — try updating instead
        _run([
            "gh", "api",
            f"repos/{GITHUB_OWNER}/{repo_name}/pages",
            "--method", "PUT",
            "-f", "build_type=workflow",
        ], check=False)

    # Trigger the workflow manually to get immediate deploy
    time.sleep(2)
    _run([
        "gh", "workflow", "run", "deploy.yml",
        "--repo", f"{GITHUB_OWNER}/{repo_name}",
    ], check=False)

    repo_url = f"https://github.com/{GITHUB_OWNER}/{repo_name}"
    live_url = f"https://{GITHUB_OWNER}.github.io/{repo_name}/"
    if custom_domain:
        live_url = f"https://{custom_domain}/"

    print(f"\n[Deployer] ✓ Live in ~60 seconds:")
    print(f"  Repo:    {repo_url}")
    print(f"  Site:    {live_url}")
    print(f"  Actions: {repo_url}/actions")

    return {
        "repo_url": repo_url,
        "live_url": live_url,
        "repo_name": repo_name,
    }
