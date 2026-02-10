from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def get_pypi_info(package_name: str) -> dict:
    try:
        with urlopen(f"https://pypi.org/pypi/{package_name}/json") as response:
            return json.loads(response.read())
    except (HTTPError, URLError):
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
