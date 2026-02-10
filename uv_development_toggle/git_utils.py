from __future__ import annotations

import json
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_github_username() -> str | None:
    try:
        result = subprocess.run(["gh", "api", "user"], capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)["login"]
    except FileNotFoundError:
        pass

    try:
        result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass

    return None


def check_github_repo_exists(username: str, repo: str) -> bool:
    try:
        urlopen(f"https://github.com/{username}/{repo}")
        return True
    except (HTTPError, URLError):
        return False


def check_github_repo_is_python_package(github_url: str) -> bool:
    match = re.match(r"https?://github\.com/([^/]+)/([^/.]+)(\.git)?", github_url)
    if not match:
        return False

    username, repo = match.groups()[:2]
    indicators = ["pyproject.toml", "setup.py", "setup.cfg"]
    for fname in indicators:
        api_url = f"https://api.github.com/repos/{username}/{repo}/contents/{fname}"
        try:
            req = Request(api_url, method="HEAD")
            urlopen(req)
            return True
        except HTTPError as e:
            if e.code == 404:
                continue

            return False
        except URLError:
            return False

    return False
