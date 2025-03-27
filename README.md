# Python Uv Development Package Toggler

A utility script for easily switching between local development and published sources for Python packages in your `pyproject.toml`.

## Features

- Automatically toggles between local development paths and GitHub sources
- Preserves TOML file comments and structure
- Automatically clones repositories when switching to local development
- Supports branch tracking
- Falls back to PyPI metadata if direct GitHub repository is not found
- Integrates with GitHub CLI for username detection
- Creates necessary TOML structure (`tool.uv.sources`) if it doesn't exist
- Automatically runs `uv sync --upgrade-package` after successful updates

## Installation

```shell
pip install uv-development-toggle
```

## Usage

To toggle a package [activemodel](https://github.com/iloveitaly/activemodel/):

```shell
uv-development-toggle activemodel --local
```

Then, after you push to a custom branch, reference the branch in your `pyproject.toml`:

```shell
uv-development-toggle activemodel --published
```

To revert a package to PyPI:

```shell
uv-development-toggle activemodel --pypi
```

This will:

1. Check if the package exists in your `PYTHON_DEVELOPMENT_TOGGLE` directory
2. If switching to local and the repository doesn't exist, clone it automatically (attempts to determine the repo URL from pypi information)
3. Update your `pyproject.toml` with the appropriate source configuration (creating the `tool.uv.sources` structure if needed)
4. Preserve any existing branch information when toggling
5. Automatically run `uv sync --upgrade-package <package_name>` to apply the changes

### Arguments

- `MODULE_NAME`: The name of the Python module to toggle
- `--local`: Force using local development path
- `--published`: Force using published source
- `--pypi`: Revert to default PyPI source

### Environment Variables

- `PYTHON_DEVELOPMENT_TOGGLE`: Directory for local development repositories (default: "pypi")
