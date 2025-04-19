import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import rich.console
import rich.logging
import tomlkit

# Setup rich console for output
console = rich.console.Console()

# Setup better logging with rich
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
    format="%(message)s",
    handlers=[
        rich.logging.RichHandler(
            rich_tracebacks=True, markup=True, show_time=False, show_path=False
        )
    ],
)

logger = logging.getLogger(__name__)


def display_status(status_type, module_name, details=None):
    """
    Display a formatted status message using rich console.

    Args:
        status_type: Type of status ('source_path', 'source_git', 'source_other', 'pypi', 'pypi_already',
                                    'error', 'warning', 'info', 'found_editable')
        module_name: Name of the module being processed
        details: Additional details or data to display (e.g., source configuration)
    """
    if status_type == "source_path":
        console.print(
            f"[bold green]✓[/bold green] Set [cyan]{module_name}[/cyan] source to local path: [yellow]{details['path']}[/yellow]"
        )
    elif status_type == "source_git":
        rev_info = (
            f" (branch: [magenta]{details.get('rev')}[/magenta])"
            if details.get("rev")
            else ""
        )
        console.print(
            f"[bold green]✓[/bold green] Set [cyan]{module_name}[/cyan] source to Git repo: [blue]{details['git']}[/blue]{rev_info}"
        )
    elif status_type == "source_other":
        console.print(
            f"[bold green]✓[/bold green] Set [cyan]{module_name}[/cyan] source to: {details}"
        )
    elif status_type == "pypi":
        console.print(
            f"[bold green]✓[/bold green] Removing custom source for [cyan]{module_name}[/cyan] to use [magenta]PyPI version[/magenta]"
        )
    elif status_type == "pypi_already":
        console.print(
            f"[bold green]✓[/bold green] Already using [magenta]PyPI version[/magenta] for [cyan]{module_name}[/cyan]"
        )
    elif status_type == "error":
        console.print(
            f"[bold red]✗[/bold red] Error: {details} for [cyan]{module_name}[/cyan]"
        )
    elif status_type == "warning":
        console.print(
            f"[bold yellow]![/bold yellow] Warning: {details} for [cyan]{module_name}[/cyan]"
        )
    elif status_type == "info":
        console.print(
            f"[bold blue]i[/bold blue] {details} for [cyan]{module_name}[/cyan]"
        )
    elif status_type == "found_editable":
        console.print(
            f"[bold yellow]![/bold yellow] Found editable package [cyan]{module_name}[/cyan]: [yellow]{details.get('path')}[/yellow]"
        )


def get_github_username() -> str:
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
    except:
        logger.debug("Repository not found")
        return False


def get_pypi_info(package_name: str) -> dict:
    logger.debug(f"Fetching PyPI data for {package_name}")
    try:
        with urlopen(f"https://pypi.org/pypi/{package_name}/json") as response:
            data = json.loads(response.read())
            logger.debug("Successfully fetched PyPI data")
            return data
    except:
        logger.debug("Failed to fetch PyPI data")
        return {}


def get_pypi_homepage(package_name: str) -> str:
    data = get_pypi_info(package_name)
    homepage = data.get("info", {}).get("home_page", "")

    # Ensure homepage is not None
    homepage = homepage or ""

    # Check if homepage contains github.com
    if homepage and "github.com" in homepage:
        return homepage

    # Check all project URLs for GitHub links
    project_urls = data.get("info", {}).get("project_urls") or {}

    # First try the repository link as priority
    if (
        "repository" in project_urls
        and project_urls["repository"]
        and "github.com" in project_urls["repository"]
    ):
        return project_urls["repository"]

    # Then look in all other project links
    for url_name, url in project_urls.items():
        if url and "github.com" in url:
            return url

    # Return homepage even if it's not a GitHub URL, or empty string
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

    # Ensure the required sections exist
    if "tool" not in config:
        config["tool"] = tomlkit.table()

    if "uv" not in config["tool"]:
        config["tool"]["uv"] = tomlkit.table()

    if "sources" not in config["tool"]["uv"]:
        config["tool"]["uv"]["sources"] = tomlkit.table()

    sources = config["tool"]["uv"]["sources"]
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

    # Check if the structure exists
    if (
        "tool" not in config
        or "uv" not in config["tool"]
        or "sources" not in config["tool"]["uv"]
    ):
        display_status("info", "pyproject.toml", "No uv sources configuration found")
        return []

    sources = config["tool"]["uv"]["sources"]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "module", nargs="?", help="Module name in pyproject.toml to toggle"
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local editable path, and clone repo if necessary",
    )
    parser.add_argument(
        "--published",
        action="store_true",
        help="Use github source",
    )
    parser.add_argument(
        "--pypi",
        action="store_true",
        help="Use PyPI published version",
    )
    parser.add_argument(
        "--remove-editable",
        action="store_true",
        help="Find all editable packages and switch them to published sources",
    )

    args = parser.parse_args()

    if args.remove_editable:
        console.print("[bold]Searching for editable packages...[/bold]")
        packages = find_and_update_editable_sources(switch_to_published=True)
        if packages:
            console.print(
                f"[bold green]✓[/bold green] Converted [cyan]{len(packages)}[/cyan] editable packages to published sources"
            )
        return

    # If 'all' is passed as the module and --local is NOT set, apply --published or --pypi to all editable packages
    if args.module == "all" and not args.local:
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
            if args.pypi:
                toggle_module_source(
                    pkg, force_local=False, force_published=False, force_pypi=True
                )
            else:
                toggle_module_source(
                    pkg, force_local=False, force_published=True, force_pypi=False
                )
        console.print(
            f"[bold green]✓[/bold green] Updated [cyan]{len(editable_packages)}[/cyan] editable packages to "
            + (
                "[magenta]PyPI[/magenta]"
                if args.pypi
                else "[blue]published sources[/blue]"
            )
        )
        return

    if not args.module:
        parser.error("module name is required unless using --remove-editable")

    toggle_module_source(args.module, args.local, args.published, args.pypi)


if __name__ == "__main__":
    main()
