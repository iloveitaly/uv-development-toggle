import json
import os
import subprocess
import tomllib
from http.client import HTTPMessage
from pathlib import Path
from urllib.error import HTTPError, URLError

import click
import pytest
import tomlkit
from click.testing import CliRunner

import uv_development_toggle as toggle


def write_pyproject(pyproject_path: Path, sources: dict) -> None:
    config = tomlkit.document()
    config["project"] = {"name": "demo", "version": "0.1.0"}

    tool = tomlkit.table()
    uv_table = tomlkit.table()
    uv_table["sources"] = sources
    tool["uv"] = uv_table
    config["tool"] = tool

    pyproject_path.write_text(tomlkit.dumps(config))


def create_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def create_git_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], check=True, cwd=repo_path)
    (repo_path / "README.md").write_text("demo")
    subprocess.run(["git", "add", "README.md"], check=True, cwd=repo_path)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=demo",
            "-c",
            "user.email=demo@example.com",
            "commit",
            "-m",
            "initial",
        ],
        check=True,
        cwd=repo_path,
    )


def create_git_repo_with_branch(repo_path: Path, branch_name: str) -> None:
    create_git_repo(repo_path)
    subprocess.run(["git", "checkout", "-b", branch_name], check=True, cwd=repo_path)


def test_display_status_variants(capsys: pytest.CaptureFixture[str]) -> None:
    toggle.display_status("source_path", "pkg", {"path": "/tmp/pkg"})
    toggle.display_status(
        "source_git", "pkg", {"git": "https://example.com", "rev": "dev"}
    )
    toggle.display_status("source_other", "pkg", "custom")
    toggle.display_status("pypi", "pkg")
    toggle.display_status("pypi_already", "pkg")
    toggle.display_status("error", "pkg", "bad")
    toggle.display_status("warning", "pkg", "warn")
    toggle.display_status("info", "pkg", "info")
    toggle.display_status("found_editable", "pkg", {"path": "/tmp/pkg"})

    output = capsys.readouterr().out

    assert "Set pkg source to local path: /tmp/pkg" in output
    assert "Set pkg source to Git repo: https://example.com" in output
    assert "Set pkg source to: custom" in output
    assert "Removing custom source for pkg" in output
    assert "Already using PyPI version for pkg" in output
    assert "Error: bad for pkg" in output
    assert "Warning: warn for pkg" in output
    assert "info for pkg" in output
    assert "Found editable package pkg: /tmp/pkg" in output


def test_get_github_username_from_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_path = tmp_path / "bin"
    bin_path.mkdir()

    gh_path = bin_path / "gh"
    create_executable(gh_path, '#!/usr/bin/env sh\necho \'{"login": "alice"}\'\n')

    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ.get('PATH', '')}")

    assert toggle.get_github_username() == "alice"


def test_get_github_username_fallback_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_path = tmp_path / "bin"
    bin_path.mkdir()

    gh_path = bin_path / "gh"
    create_executable(gh_path, "#!/usr/bin/env sh\nexit 1\n")

    git_path = bin_path / "git"
    create_executable(
        git_path,
        "#!/usr/bin/env sh\n"
        'if [ "$1" = "config" ] && [ "$2" = "user.name" ]; then\n'
        '  echo "bob"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
    )

    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ.get('PATH', '')}")

    assert toggle.get_github_username() == "bob"


def test_check_github_repo_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen_success(_url: str) -> object:
        return object()

    def fake_urlopen_fail(_url: str) -> None:
        raise HTTPError(_url, 404, "not found", HTTPMessage(), None)

    monkeypatch.setattr(toggle, "urlopen", fake_urlopen_success)
    assert toggle.check_github_repo_exists("alice", "repo") is True

    monkeypatch.setattr(toggle, "urlopen", fake_urlopen_fail)
    assert toggle.check_github_repo_exists("alice", "repo") is False


def test_get_pypi_info_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"info": {"home_page": "https://example.com"}}).encode()

    def fake_urlopen_success(_url: str) -> FakeResponse:
        return FakeResponse()

    def fake_urlopen_fail(_url: str) -> None:
        raise URLError("fail")

    monkeypatch.setattr(toggle, "urlopen", fake_urlopen_success)
    assert toggle.get_pypi_info("demo")["info"]["home_page"] == "https://example.com"

    monkeypatch.setattr(toggle, "urlopen", fake_urlopen_fail)
    assert toggle.get_pypi_info("demo") == {}


def test_get_pypi_homepage_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        toggle,
        "get_pypi_info",
        lambda _name: {"info": {"home_page": "https://github.com/acme/demo"}},
    )
    assert toggle.get_pypi_homepage("demo") == "https://github.com/acme/demo"

    monkeypatch.setattr(
        toggle,
        "get_pypi_info",
        lambda _name: {
            "info": {
                "home_page": "https://example.com",
                "project_urls": {"repository": "https://github.com/acme/demo"},
            }
        },
    )
    assert toggle.get_pypi_homepage("demo") == "https://github.com/acme/demo"

    monkeypatch.setattr(
        toggle,
        "get_pypi_info",
        lambda _name: {
            "info": {
                "home_page": "https://example.com",
                "project_urls": {"docs": "https://github.com/acme/demo"},
            }
        },
    )
    assert toggle.get_pypi_homepage("demo") == "https://github.com/acme/demo"

    monkeypatch.setattr(
        toggle,
        "get_pypi_info",
        lambda _name: {"info": {"home_page": "https://example.com"}},
    )
    assert toggle.get_pypi_homepage("demo") == "https://example.com"


def test_clone_repo_local(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    create_git_repo(source_repo)

    target_repo = tmp_path / "target"
    toggle.clone_repo(str(source_repo), target_repo)

    assert (target_repo / ".git").exists()


def test_get_current_branch(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    create_git_repo_with_branch(repo_path, "feature")

    assert toggle.get_current_branch(repo_path) == "feature"


def test_uv_update_package_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_path = tmp_path / "bin"
    bin_path.mkdir()

    uv_path = bin_path / "uv"
    create_executable(uv_path, "#!/usr/bin/env sh\nexit 0\n")
    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ.get('PATH', '')}")

    assert toggle.uv_update_package("demo") is True

    create_executable(uv_path, "#!/usr/bin/env sh\necho fail 1>&2\nexit 1\n")
    assert toggle.uv_update_package("demo") is False


def test_uv_update_package_missing_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_path = tmp_path / "bin"
    bin_path.mkdir()

    monkeypatch.setenv("PATH", str(bin_path))

    assert toggle.uv_update_package("demo") is False


def test_check_github_repo_is_python_package(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object) -> object:
        url = getattr(req, "full_url", "")
        if url.endswith("pyproject.toml"):
            return object()
        raise HTTPError(url, 404, "not found", HTTPMessage(), None)

    monkeypatch.setattr(toggle, "urlopen", fake_urlopen)

    assert (
        toggle.check_github_repo_is_python_package("https://github.com/acme/demo.git")
        is True
    )

    def fake_urlopen_missing(req: object) -> None:
        url = getattr(req, "full_url", "")
        raise HTTPError(url, 404, "not found", HTTPMessage(), None)

    monkeypatch.setattr(toggle, "urlopen", fake_urlopen_missing)

    assert (
        toggle.check_github_repo_is_python_package("https://github.com/acme/demo.git")
        is False
    )

    assert toggle.check_github_repo_is_python_package("not-a-url") is False


def test_toggle_module_source_force_pypi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, {"demo": {"git": "https://example.com/demo.git"}})

    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    uv_path = bin_path / "uv"
    create_executable(uv_path, "#!/usr/bin/env sh\nexit 0\n")
    monkeypatch.setenv("PATH", str(bin_path))

    monkeypatch.chdir(tmp_path)
    toggle.toggle_module_source("demo", force_pypi=True)

    updated = tomllib.loads(pyproject_path.read_text())
    sources = updated.get("tool", {}).get("uv", {}).get("sources", {})
    assert "demo" not in sources


def test_toggle_module_source_switches_to_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, {"demo": {"git": "https://example.com/demo.git"}})

    dev_toggle = tmp_path / "dev"
    local_repo = dev_toggle / "demo"
    create_git_repo(local_repo)

    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    uv_path = bin_path / "uv"
    create_executable(uv_path, "#!/usr/bin/env sh\nexit 0\n")

    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PYTHON_DEVELOPMENT_TOGGLE", str(dev_toggle))
    monkeypatch.setattr(toggle, "get_github_username", lambda: None)
    monkeypatch.setattr(toggle, "get_pypi_homepage", lambda _name: "")

    monkeypatch.chdir(tmp_path)
    toggle.toggle_module_source("demo")

    updated = tomllib.loads(pyproject_path.read_text())
    sources = updated.get("tool", {}).get("uv", {}).get("sources", {})

    assert sources["demo"]["path"] == str(local_repo)
    assert sources["demo"]["editable"] is True


def test_toggle_module_source_force_published_uses_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, {"demo": {"path": "/tmp/demo", "editable": True}})

    dev_toggle = tmp_path / "dev"
    local_repo = dev_toggle / "demo"
    create_git_repo_with_branch(local_repo, "feature")

    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    uv_path = bin_path / "uv"
    create_executable(uv_path, "#!/usr/bin/env sh\nexit 0\n")

    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PYTHON_DEVELOPMENT_TOGGLE", str(dev_toggle))
    monkeypatch.setattr(toggle, "get_github_username", lambda: "alice")
    monkeypatch.setattr(toggle, "check_github_repo_exists", lambda _u, _r: True)
    monkeypatch.setattr(toggle, "check_github_repo_is_python_package", lambda _u: True)

    monkeypatch.chdir(tmp_path)
    toggle.toggle_module_source("demo", force_published=True)

    updated = tomllib.loads(pyproject_path.read_text())
    source = updated["tool"]["uv"]["sources"]["demo"]
    assert source["git"] == "https://github.com/alice/demo.git"
    assert source["rev"] == "feature"


def test_toggle_module_source_missing_local_and_no_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, {})

    dev_toggle = tmp_path / "dev"
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    uv_path = bin_path / "uv"
    create_executable(uv_path, "#!/usr/bin/env sh\nexit 0\n")

    monkeypatch.setenv("PATH", f"{bin_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PYTHON_DEVELOPMENT_TOGGLE", str(dev_toggle))
    monkeypatch.setattr(toggle, "get_github_username", lambda: None)
    monkeypatch.setattr(toggle, "get_pypi_homepage", lambda _name: "")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        toggle.toggle_module_source("demo")


def test_find_and_update_editable_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(
        pyproject_path,
        {
            "demo": {"path": "/tmp/demo", "editable": True},
            "other": {"git": "https://example.com/other.git"},
        },
    )

    monkeypatch.chdir(tmp_path)
    assert toggle.find_and_update_editable_sources(switch_to_published=False) == [
        "demo"
    ]

    called = []

    def fake_toggle(
        package_name: str, force_local: bool, force_published: bool
    ) -> None:
        called.append((package_name, force_local, force_published))

    monkeypatch.setattr(toggle, "toggle_module_source", fake_toggle)

    assert toggle.find_and_update_editable_sources(switch_to_published=True) == ["demo"]
    assert called == [("demo", False, True)]


def test_find_and_update_editable_sources_no_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, {})

    monkeypatch.chdir(tmp_path)
    assert toggle.find_and_update_editable_sources(switch_to_published=False) == []


def test_main_all_force_pypi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    write_pyproject(pyproject_path, {"demo": {"path": "/tmp/demo", "editable": True}})

    called = []

    def fake_toggle(
        module_name: str, force_local: bool, force_published: bool, force_pypi: bool
    ) -> None:
        called.append((module_name, force_local, force_published, force_pypi))

    monkeypatch.setattr(toggle, "toggle_module_source", fake_toggle)
    monkeypatch.chdir(tmp_path)

    toggle.main(
        "all",
        force_local=False,
        force_published=False,
        force_pypi=True,
        remove_editable=False,
    )
    assert called == [("demo", False, False, True)]


def test_cli_requires_module() -> None:
    runner = CliRunner()
    result = runner.invoke(toggle.cli, [])

    assert result.exit_code != 0
    assert "module name is required" in result.output
