"""Test get_pypi_homepage function for proper URL prioritization."""

import pytest
from unittest.mock import patch
from uv_development_toggle import get_pypi_homepage


def test_get_pypi_homepage_prioritizes_source_over_changelog():
    """Test that Source URL is preferred over Changelog URL."""
    mock_data = {
        "info": {
            "home_page": "",
            "project_urls": {
                "Documentation": "https://github.com/un33k/python-ipware#readme",
                "Issues": "https://github.com/un33k/python-ipware/issues",
                "Source": "https://github.com/un33k/python-ipware",
                "Changelog": "https://github.com/un33k/python-ipware/blob/main/CHANGELOG.md",
            },
        }
    }

    with patch("uv_development_toggle.get_pypi_info", return_value=mock_data):
        result = get_pypi_homepage("python-ipware")
        assert result == "https://github.com/un33k/python-ipware"
        assert "/blob/" not in result


def test_get_pypi_homepage_prioritizes_repository():
    """Test that repository key takes priority."""
    mock_data = {
        "info": {
            "home_page": "",
            "project_urls": {
                "repository": "https://github.com/user/correct-repo",
                "Source": "https://github.com/user/other-repo",
                "Changelog": "https://github.com/user/correct-repo/blob/main/CHANGELOG.md",
            },
        }
    }

    with patch("uv_development_toggle.get_pypi_info", return_value=mock_data):
        result = get_pypi_homepage("test-package")
        assert result == "https://github.com/user/correct-repo"


def test_get_pypi_homepage_skips_blob_urls():
    """Test that URLs pointing to files (with /blob/) are skipped."""
    mock_data = {
        "info": {
            "home_page": "",
            "project_urls": {
                "Changelog": "https://github.com/user/repo/blob/main/CHANGELOG.md",
                "Documentation": "https://github.com/user/repo/blob/main/README.md",
                "Home": "https://github.com/user/repo",
            },
        }
    }

    with patch("uv_development_toggle.get_pypi_info", return_value=mock_data):
        result = get_pypi_homepage("test-package")
        # Should return the Home URL since it doesn't have /blob/
        assert result == "https://github.com/user/repo"


def test_get_pypi_homepage_case_insensitive():
    """Test that URL key matching is case-insensitive."""
    mock_data = {
        "info": {
            "home_page": "",
            "project_urls": {
                "source code": "https://github.com/user/repo",
                "CHANGELOG": "https://github.com/user/repo/blob/main/CHANGELOG.md",
            },
        }
    }

    with patch("uv_development_toggle.get_pypi_info", return_value=mock_data):
        result = get_pypi_homepage("test-package")
        assert result == "https://github.com/user/repo"


def test_get_pypi_homepage_with_homepage():
    """Test that homepage is returned if it contains github.com."""
    mock_data = {
        "info": {
            "home_page": "https://github.com/user/repo",
            "project_urls": {},
        }
    }

    with patch("uv_development_toggle.get_pypi_info", return_value=mock_data):
        result = get_pypi_homepage("test-package")
        assert result == "https://github.com/user/repo"


def test_get_pypi_homepage_no_github_url():
    """Test behavior when no GitHub URL is found."""
    mock_data = {
        "info": {
            "home_page": "https://example.com",
            "project_urls": {
                "Documentation": "https://docs.example.com",
            },
        }
    }

    with patch("uv_development_toggle.get_pypi_info", return_value=mock_data):
        result = get_pypi_homepage("test-package")
        assert result == "https://example.com"


def test_get_pypi_homepage_empty_data():
    """Test behavior with empty PyPI data."""
    mock_data = {"info": {}}

    with patch("uv_development_toggle.get_pypi_info", return_value=mock_data):
        result = get_pypi_homepage("test-package")
        assert result == ""
