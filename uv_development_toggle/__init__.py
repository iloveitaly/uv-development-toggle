import logging
import os
import subprocess
import sys
from pathlib import Path

import click
import tomlkit

from uv_development_toggle.git_utils import (
    check_github_repo_exists,
    check_github_repo_is_python_package,
    get_github_username,
)
from uv_development_toggle.pypi import get_pypi_homepage
from uv_development_toggle.status import display_status, format_status_label

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
    format="%(message)s",
)

logger = logging.getLogger(__name__)


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
    config = tomlkit.loads(pyproject_path.read_text())

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
        pyproject_path.write_text(tomlkit.dumps(config))

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
    pyproject_path.write_text(tomlkit.dumps(config))

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
    config = tomlkit.loads(pyproject_path.read_text())

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
        config = tomlkit.loads(pyproject_path.read_text())
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
