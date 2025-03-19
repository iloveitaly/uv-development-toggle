
# Python Development Source Toggler

A utility script for easily switching between local development and published sources for Python packages in your `pyproject.toml`.

## Features

- Automatically toggles between local development paths and GitHub sources
- Preserves TOML file comments and structure
- Automatically clones repositories when switching to local development
- Supports branch tracking
- Falls back to PyPI metadata if direct GitHub repository is not found
- Integrates with GitHub CLI for username detection

## Installation


pip install -r requirements.txt


## Usage

To toggle a module named "activemodel":

```shell
pip install uv-development-toggle
uv-development-toggle activemodel --published
```

This will:

1. Check if the package exists in your `PYTHON_DEVELOPMENT_TOGGLE` directory
2. If switching to local and the repository doesn't exist, clone it automatically (attempts to determine the repo URL from pypi information)
3. Update your `pyproject.toml` with the appropriate source configuration
4. Preserve any existing branch information when toggling

### Arguments

- `MODULE_NAME`: The name of the Python module to toggle
- `--local`: Force using local development path
- `--published`: Force using published source

### Environment Variables

- `PYTHON_DEVELOPMENT_TOGGLE`: Directory for local development repositories (default: "pypi")
