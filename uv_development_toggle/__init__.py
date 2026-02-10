import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import click
import tomlkit

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
    format="%(message)s",
)

logger = logging.getLogger(__name__)


def format_status_label(label: str, color: str) -> str:
    return click.style(label, fg=color, bold=True)


def display_status(status_type, module_name, details=None):
    if details is None:
        details = {}
    """
    Display a formatted status message using rich console.

    Args:
        status_type: Type of status ('source_path', 'source_git', 'source_other', 'pypi', 'pypi_already',
                                    'error', 'warning', 'info', 'found_editable')
        module_name: Name of the module being processed
        details: Additional details or data to display (e.g., source configuration)
    """
    if status_type == "source_path":
        message = f"Set {module_name} source to local path: {details['path']}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "source_git":
        rev_info = f" (branch: {details.get('rev')})" if details.get("rev") else ""
        message = f"Set {module_name} source to Git repo: {details['git']}{rev_info}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "source_other":
        message = f"Set {module_name} source to: {details}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "pypi":
        message = f"Removing custom source for {module_name} to use PyPI version"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "pypi_already":
        message = f"Already using PyPI version for {module_name}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
    elif status_type == "error":
        message = f"Error: {details} for {module_name}"
        click.echo(f"{format_status_label('ERROR', 'red')} {message}")
    elif status_type == "warning":
        message = f"Warning: {details} for {module_name}"
        click.echo(f"{format_status_label('WARN', 'yellow')} {message}")
    elif status_type == "info":
        message = f"{details} for {module_name}"
        click.echo(f"{format_status_label('INFO', 'blue')} {message}")
    elif status_type == "found_editable":
        message = f"Found editable package {module_name}: {details.get('path')}"
        click.echo(f"{format_status_label('WARN', 'yellow')} {message}")


def get_github_username() -> str | None:
    logger.debug("Attempting to get GitHub username")
    # Try gh cli first
    try:
        result = subprocess.run(["gh", "api", "user"], capture_output=True, text=True)
        if result.returncode == 0:
            username = json.loads(result.stdout)["login"]
            logger.debug(f"Found username via gh cli: {username}")
            return username
    except FileNotFoundError:
        logger.debug("gh cli not found, trying git config")

    # Fall back to git config
    try:
        result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True
        )
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
    except (HTTPError, URLError):
        logger.debug("Repository not found")
        return False


def get_pypi_info(package_name: str) -> dict:
    logger.debug(f"Fetching PyPI data for {package_name}")
    try:
        with urlopen(f"https://pypi.org/pypi/{package_name}/json") as response:
            data = json.loads(response.read())
            logger.debug("Successfully fetched PyPI data")
            return data
    except (HTTPError, URLError):
        logger.debug("Failed to fetch PyPI data")
        return {}


def is_repository_url(url: str) -> bool:
    if "github.com" not in url:
        return False

    return "/blob/" not in url and "/tree/" not in url


def normalize_project_url_key(key: str) -> str:
    return key.strip().lower()


def get_pypi_homepage(package_name: str) -> str:
    data = get_pypi_info(package_name)
    homepage = data.get("info", {}).get("home_page", "") or ""

    if homepage and is_repository_url(homepage):
        return homepage

    project_urls = data.get("info", {}).get("project_urls") or {}
    normalized_urls = {
        normalize_project_url_key(key): url for key, url in project_urls.items()
    }

    priority_keys = ("repository", "source", "source code")
    for key in priority_keys:
        url = normalized_urls.get(key, "")
        if url and is_repository_url(url):
            return url

    skip_keys = (
        "changelog",
        "documentation",
        "docs",
        "issues",
        "bug tracker",
        "bugtracker",
    )
    for key, url in normalized_urls.items():
        if key in skip_keys:
            continue

        if url and is_repository_url(url):
            return url

    for url in normalized_urls.values():
        if url and "github.com" in url:
            return url

    return homepage


def clone_repo(github_url: str, target_path: Path):
    logger.info(f"Cloning {github_url} into {target_path}")
    subprocess.run(["git", "clone", github_url, str(target_path)], check=True)


def get_current_branch(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(repo_path),
    )
    return result.stdout.strip()


def uv_update_package(package_name):
    """
    Run uv sync to update the package after modifying pyproject.toml

    This is more targeted than a full uv sync as it only updates the specific
    package and doesn't drop other groups that were previously installed.
    """
    try:
        logger.info(f"Upgrading package reference {package_name}...")
        result = subprocess.run(
            ["uv", "sync", "--upgrade-package", package_name],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info(f"Successfully upgraded {package_name}")
        logger.debug(f"Sync result: {result.stdout.strip()} {result.stderr.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error syncing package {package_name}: {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        logger.warning(
            "'uv' command not found. Make sure it's installed and in your PATH."
        )
        return False


def check_github_repo_is_python_package(github_url: str) -> bool:
    """
    Checks if a GitHub repository contains a pyproject.toml, setup.py, or setup.cfg file in its root via the GitHub API.
    """
    match = re.match(r"https?://github\.com/([^/]+)/([^/.]+)(\.git)?", github_url)
    if not match:
        logger.warning(f"Could not parse username/repo from URL: {github_url}")
        return False

    username, repo = match.groups()[:2]
    indicators = ["pyproject.toml", "setup.py", "setup.cfg"]
    for fname in indicators:
        api_url = f"https://api.github.com/repos/{username}/{repo}/contents/{fname}"
        try:
            req = Request(api_url, method="HEAD")
            urlopen(req)
            logger.debug(f"Found {fname} in {username}/{repo}")
            return True
        except HTTPError as e:
            if e.code == 404:
                logger.debug(f"{fname} not found in {username}/{repo}")
            else:
                logger.warning(f"HTTP error checking for {fname}: {e.code} {e.reason}")
        except URLError as e:
            logger.error(f"URL error connecting to GitHub API: {e.reason}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking for {fname}: {e}")
            return False
    logger.debug(f"No Python package indicators found in {username}/{repo}")
    return False


def toggle_module_source(
    module_name: str,
    force_local: bool = False,
    force_published: bool = False,
    force_pypi: bool = False,
):
    pyproject_path = Path("pyproject.toml")

    # Check if the pyproject.toml exists
    if not pyproject_path.exists():
        logger.error("No pyproject.toml found, are you in the right folder?")
        sys.exit(1)

    # Read with tomlkit to preserve comments and structure
    with open(pyproject_path) as f:
        config = tomlkit.load(f)

    tool_config = config.setdefault("tool", tomlkit.table())
    uv_config = tool_config.setdefault("uv", tomlkit.table())
    sources = uv_config.setdefault("sources", tomlkit.table())
    current_source = sources.get(module_name, {})

    # Handle PyPI option
    if force_pypi:
        # For PyPI, we remove the source entry or set it to {} to use default PyPI source
        if module_name in sources:
            display_status("pypi", module_name)
            del sources[module_name]
        else:
            display_status("pypi_already", module_name)

        # Write back with preserved comments
        with open(pyproject_path, "w") as f:
            tomlkit.dump(config, f)

        # Update the package with uv sync even when reverting to PyPI
        uv_update_package(module_name)

        return

    dev_toggle_dir = os.environ.get("PYTHON_DEVELOPMENT_TOGGLE", "pypi")
    local_path_default = Path(f"{dev_toggle_dir}/{module_name}")
    local_path_dash = Path(f"{dev_toggle_dir}/{module_name.replace('_', '-')}")
    local_path_underscore = Path(f"{dev_toggle_dir}/{module_name.replace('-', '_')}")

    if local_path_default.exists():
        local_path = local_path_default
    elif local_path_dash.exists():
        local_path = local_path_dash
    elif local_path_underscore.exists():
        local_path = local_path_underscore
    else:
        local_path = local_path_default

    # Get current branch if local repo exists
    current_branch = None
    if local_path.exists():
        current_branch = get_current_branch(local_path)
        if current_branch in ("master", "main"):
            current_branch = None

    # Try to find the correct GitHub source
    github_url = None
    username = get_github_username()

    # Try username/module_name convention first
    repo_valid = False
    if username and check_github_repo_exists(username, module_name):
        candidate_url = f"https://github.com/{username}/{module_name}.git"
        if check_github_repo_is_python_package(candidate_url):
            github_url = candidate_url
            repo_valid = True
        else:
            # Try PyPI homepage as fallback if user repo is not valid
            pypi_homepage = get_pypi_homepage(module_name)
            if "github.com" in pypi_homepage:
                pypi_url = pypi_homepage
                if not pypi_url.endswith(".git"):
                    pypi_url += ".git"
                if check_github_repo_is_python_package(pypi_url):
                    github_url = pypi_url
                    repo_valid = True
    else:
        # Fallback to PyPI homepage
        pypi_homepage = get_pypi_homepage(module_name)
        if "github.com" in pypi_homepage:
            pypi_url = pypi_homepage
            if not pypi_url.endswith(".git"):
                pypi_url += ".git"
            if check_github_repo_is_python_package(pypi_url):
                github_url = pypi_url
                repo_valid = True

    if not github_url:
        display_status("warning", module_name, "Could not determine GitHub URL")
        if not local_path.exists():
            display_status(
                "error",
                module_name,
                f"Local path {local_path} does not exist and GitHub URL detection failed",
            )
            sys.exit(1)

    published_source = (
        {"git": github_url, "rev": current_branch}
        if current_branch
        else {"git": github_url}
    )
    local_source = {"path": str(local_path), "editable": True}

    if force_local or (not force_published and "git" in current_source):
        new_source = local_source
        if not local_path.exists():
            if not github_url:
                display_status(
                    "error",
                    module_name,
                    f"Local path {local_path} does not exist and cannot clone without a GitHub URL.",
                )
                sys.exit(1)
            if not repo_valid:
                display_status(
                    "error",
                    module_name,
                    f"Neither {username}/{module_name} nor the PyPI GitHub reference appear to be valid Python packages (missing pyproject.toml/setup.py/setup.cfg). Cannot clone.",
                )
                sys.exit(1)
            display_status(
                "info", module_name, f"Local path {local_path} does not exist"
            )
            clone_repo(github_url, local_path)
    else:
        new_source = published_source

    sources[module_name] = new_source

    # Write back with preserved comments
    with open(pyproject_path, "w") as f:
        tomlkit.dump(config, f)

    # Update the package with uv sync
    uv_update_package(module_name)

    # Format and output the source change information
    if "path" in new_source:
        display_status("source_path", module_name, new_source)
    elif "git" in new_source:
        display_status("source_git", module_name, new_source)
    else:
        display_status("source_other", module_name, new_source)


def find_and_update_editable_sources(switch_to_published=False):
    """
    Find all packages with editable sources in pyproject.toml and update them.

    Args:
        switch_to_published: If True, switch to published sources, otherwise just report.

    Returns:
        List of package names that were updated
    """
    pyproject_path = Path("pyproject.toml")

    # Check if the pyproject.toml exists
    if not pyproject_path.exists():
        display_status(
            "error", "pyproject.toml", "File not found, are you in the right folder?"
        )
        sys.exit(1)

    # Read with tomlkit to preserve comments and structure
    with open(pyproject_path) as f:
        config = tomlkit.load(f)

    sources = config.get("tool", {}).get("uv", {}).get("sources")
    if not sources:
        display_status("info", "pyproject.toml", "No uv sources configuration found")
        return []
    editable_packages = []

    # Find all editable sources
    for package_name, source_config in sources.items():
        if isinstance(source_config, dict) and source_config.get("editable"):
            editable_packages.append(package_name)
            display_status("found_editable", package_name, source_config)

            if switch_to_published:
                # Process each editable package to convert to published source
                toggle_module_source(
                    package_name, force_local=False, force_published=True
                )

    if not editable_packages:
        display_status("info", "pyproject.toml", "No editable packages found")

    return editable_packages


def main(module, force_local, force_published, force_pypi, remove_editable):
    if remove_editable:
        click.echo("Searching for editable packages...")
        packages = find_and_update_editable_sources(switch_to_published=True)
        if packages:
            message = (
                f"Converted {len(packages)} editable packages to published sources"
            )
            click.echo(f"{format_status_label('OK', 'green')} {message}")
        return

    # If 'all' is passed as the module and --local is NOT set, apply --published or --pypi to all editable packages
    if module == "all" and not force_local:
        pyproject_path = Path("pyproject.toml")
        if not pyproject_path.exists():
            display_status(
                "error",
                "pyproject.toml",
                "File not found, are you in the right folder?",
            )
            sys.exit(1)
        with open(pyproject_path) as f:
            config = tomlkit.load(f)
        sources = config.get("tool", {}).get("uv", {}).get("sources", {})
        editable_packages = [
            pkg
            for pkg, src in sources.items()
            if isinstance(src, dict) and src.get("editable")
        ]
        if not editable_packages:
            display_status("info", "pyproject.toml", "No editable packages found")
            return
        for pkg in editable_packages:
            if force_pypi:
                toggle_module_source(
                    pkg, force_local=False, force_published=False, force_pypi=True
                )
            else:
                toggle_module_source(
                    pkg, force_local=False, force_published=True, force_pypi=False
                )
        destination = "PyPI" if force_pypi else "published sources"
        message = f"Updated {len(editable_packages)} editable packages to {destination}"
        click.echo(f"{format_status_label('OK', 'green')} {message}")
        return

    if not module:
        raise click.UsageError("module name is required unless using --remove-editable")

    toggle_module_source(module, force_local, force_published, force_pypi)


@click.command()
@click.argument("module", required=False)
@click.option(
    "--local",
    "force_local",
    is_flag=True,
    help="Use local editable path, and clone repo if necessary",
)
@click.option("--published", "force_published", is_flag=True, help="Use github source")
@click.option("--pypi", "force_pypi", is_flag=True, help="Use PyPI published version")
@click.option(
    "--remove-editable",
    is_flag=True,
    help="Find all editable packages and switch them to published sources",
)
def cli(module, force_local, force_published, force_pypi, remove_editable):
    main(module, force_local, force_published, force_pypi, remove_editable)
