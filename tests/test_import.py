"""Test uv-development-toggle."""

import uv_development_toggle


def test_import() -> None:
    """Test that the  can be imported."""
    assert isinstance(uv_development_toggle.__name__, str)