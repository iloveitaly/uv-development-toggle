# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "tomlkit",
#     "pdbr",
# ]
# ///

import argparse
from pathlib import Path

from pdbr import pdbr_context

import tomlkit


import argparse
import json
import logging
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def get_github_username() -> str:
    logger.debug("Attempting to get GitHub username")
    # Try gh cli first
    try:
        result = subprocess.run(['gh', 'api', 'user'], capture_output=True, text=True)
        if result.returncode == 0:
            username = json.loads(result.stdout)['login']
            logger.debug(f"Found username via gh cli: {username}")
            return username
    except FileNotFoundError:
        logger.debug("gh cli not found, trying git config")

    # Fall back to git config
    try:
        result = subprocess.run(['git', 'config', 'user.name'], capture_output=True, text=True)
        if result.returncode == 0:
            username = result.stdout.strip()
            logger.debug(f"Found username via git config: {username}")
            return username
    except FileNotFoundError:
        logger.debug("git not found")

    return None

def check_github_repo_exists(username: str, repo: str) -> bool:
    logger.debug(f"Checking if repo exists: {username}/{repo}")
    try:
        urlopen(f"https://github.com/{username}/{repo}")
        logger.debug("Repository found")
        return True
    except:
        logger.debug("Repository not found")
        return False

def get_pypi_info(package_name: str) -> dict:
    logger.debug(f"Fetching PyPI data for {package_name}")
    try:
        with urlopen(f"https://pypi.org/pypi/{package_name}/json") as response:
            data = json.loads(response.read())
            logger.debug(f"Successfully fetched PyPI data")
            return data
    except:
        logger.debug("Failed to fetch PyPI data")
        return {}

def get_pypi_homepage(package_name: str) -> str:
    data = get_pypi_info(package_name)
    homepage = data.get('info', {}).get('home_page', '')

    if not homepage:
        project_urls = data.get('info', {}).get('project_urls', {})
        homepage = project_urls.get('repository', '')

    logger.debug(f"Found homepage: {homepage}")
    return homepage

def clone_repo(github_url: str, target_path: Path):
    logger.info(f"Cloning {github_url} into {target_path}")
    subprocess.run(['git', 'clone', github_url, str(target_path)], check=True)

def get_current_branch(repo_path: Path) -> str:
    result = subprocess.run(
        ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
        capture_output=True,
        text=True,
        cwd=str(repo_path)
    )
    return result.stdout.strip()

@pdbr_context()
def toggle_module_source(
    module_name: str, force_local: bool = False, force_published: bool = False
):
    pyproject_path = Path("pyproject.toml")
    # Read with tomlkit to preserve comments and structure
    with open(pyproject_path) as f:
        config = tomlkit.load(f)

    sources = config["tool"]["uv"]["sources"]
    current_source = sources.get(module_name, {})
    local_path = Path(f"pypi/{module_name}")

    # Get current branch if local repo exists
    current_branch = None
    if local_path.exists():
        current_branch = get_current_branch(local_path)
        if current_branch in ('master', 'main'):
            current_branch = None

    # Try to find the correct GitHub source
    github_url = None
    username = get_github_username()

    if username and check_github_repo_exists(username, module_name):
        github_url = f"https://github.com/{username}/{module_name}.git"
    else:
        pypi_homepage = get_pypi_homepage(module_name)
        if 'github.com' in pypi_homepage:
            github_url = f"{pypi_homepage}.git"

    if not github_url:
        logger.error(f"Could not determine GitHub URL for {module_name}")
        return

    # Add branch to github_url if available
    if current_branch:
        published_source = {"git": github_url, "rev": current_branch}
    else:
        published_source = {"git": github_url}

    local_source = {"path": str(local_path), "editable": True}

    if force_local or (not force_published and "git" in current_source):
        new_source = local_source
        if not local_path.exists():
            logger.info(f"Local path {local_path} does not exist")
            clone_repo(github_url, local_path)
    else:
        new_source = published_source

    sources[module_name] = new_source

    # Write back with preserved comments
    with open(pyproject_path, "w") as f:
        tomlkit.dump(config, f)

    logger.info(f"Set {module_name} source to: {new_source}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("module", help="Module name to toggle")
    parser.add_argument("--local", action="store_true", help="Force local path")
    parser.add_argument(
        "--published", action="store_true", help="Force published source"
    )

    args = parser.parse_args()
    toggle_module_source(args.module, args.local, args.published)
