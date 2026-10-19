from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path


def check_git_updates(repo_dir: Path) -> bool:
    git_bin = shutil.which("git") or "git"
    fetch_cmd = [git_bin, "fetch", "origin"]
    subprocess.run(fetch_cmd, cwd=repo_dir, check=True, capture_output=True)

    head_cmd = [git_bin, "rev-parse", "HEAD"]
    head_proc = subprocess.run(head_cmd, cwd=repo_dir, check=True, capture_output=True, text=True)
    head_rev = head_proc.stdout.strip()

    upstream_cmd = [git_bin, "rev-parse", "@{u}"]
    upstream_proc = subprocess.run(upstream_cmd, cwd=repo_dir, capture_output=True, text=True)
    if upstream_proc.returncode != 0:
        return False
    upstream_rev = upstream_proc.stdout.strip()
    return head_rev != upstream_rev


def is_build_missing(repo_dir: Path) -> bool:
    web_dir = repo_dir / "web"
    modules_dir = web_dir / "node_modules"
    wasm_dir = web_dir / "src" / "lib" / "wasm"
    return (not modules_dir.is_dir()) or (not wasm_dir.is_dir())


def update_app(repo_dir: Path) -> None:
    git_bin = shutil.which("git") or "git"
    npm_bin = shutil.which("npm") or "npm"
    web_dir = repo_dir / "web"

    pull_cmd = [git_bin, "pull"]
    subprocess.run(pull_cmd, cwd=repo_dir, check=True)

    install_cmd = [npm_bin, "install"]
    subprocess.run(install_cmd, cwd=web_dir, check=True)

    wasm_cmd = [npm_bin, "run", "wasm"]
    subprocess.run(wasm_cmd, cwd=web_dir, check=True)


def run_app(repo_dir: Path) -> None:
    npm_bin = shutil.which("npm") or "npm"
    web_dir = repo_dir / "web"
    dev_cmd = [npm_bin, "run", "dev"]
    subprocess.run(dev_cmd, cwd=web_dir, check=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    repo_path = Path.home() / "projects" / "stabileo"
    if len(sys.argv) > 1:
        repo_path = Path(sys.argv[1]).resolve()

    if not repo_path.is_dir():
        logging.error("Target repository directory not found: %s", repo_path)
        sys.exit(1)

    has_updates = check_git_updates(repo_path)
    build_missing = is_build_missing(repo_path)

    if has_updates or build_missing:
        logging.info("Updating Stabileo repository and dependencies...")
        update_app(repo_path)
    else:
        logging.info("Stabileo repository is up to date.")

    logging.info("Launching Stabileo dev server...")
    run_app(repo_path)


if __name__ == "__main__":
    main()

