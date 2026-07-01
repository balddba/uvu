"""Unit tests for core.py."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any, Sequence
import pytest

from update_uv_packages.direct_dependency import DirectDependency
from update_uv_packages.package_update import PackageUpdate
from update_uv_packages.project_layout import ProjectLayout
from update_uv_packages.update_report import UpdateReport
from update_uv_packages.uv_dependency_manager import UVDependencyManager
from update_uv_packages.workspace_member import WorkspaceMember


def test_dataclass_properties() -> None:
    """Test ProjectLayout.is_workspace property."""
    root = Path("/foo")
    member = WorkspaceMember(name="m1", path=root / "m1", relative_path="m1")
    layout_standalone = ProjectLayout(
        root=root, lock_path=root / "uv.lock", workspace_members=[]
    )
    assert not layout_standalone.is_workspace

    layout_workspace = ProjectLayout(
        root=root, lock_path=root / "uv.lock", workspace_members=[member]
    )
    assert layout_workspace.is_workspace


def test_normalize_name() -> None:
    """Test normalize_name with different package casing/separators."""
    manager = UVDependencyManager()
    assert manager.normalize_name("Flask-WTF") == "flask-wtf"
    assert manager.normalize_name("flask_wtf") == "flask-wtf"
    assert manager.normalize_name("FLASK.WTF") == "flask-wtf"


def test_load_toml_success(temp_standalone_project: Path) -> None:
    """Test _load_toml parses a valid TOML file correctly.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
    """
    manager = UVDependencyManager()
    pyproject_path = temp_standalone_project / "pyproject.toml"
    data = manager._load_toml(path=pyproject_path)
    assert data["project"]["name"] == "standalone"


def test_load_toml_not_found() -> None:
    """Test _load_toml raises SystemExit when file does not exist."""
    manager = UVDependencyManager()
    with pytest.raises(SystemExit) as exc_info:
        manager._load_toml(path=Path("/nonexistent/file.toml"))
    assert exc_info.value.code == 1


def test_load_toml_permission_denied(tmp_path: Path) -> None:
    """Test _load_toml raises SystemExit on PermissionError.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    file_path = tmp_path / "noperms.toml"
    file_path.write_text("a = 1", encoding="utf-8")
    file_path.chmod(0o000)  # Remove all read/write permissions
    try:
        with pytest.raises(SystemExit) as exc_info:
            manager._load_toml(path=file_path)
        assert exc_info.value.code == 1
    finally:
        file_path.chmod(0o644)  # Restore so cleanup works


def test_load_toml_invalid_format(tmp_path: Path) -> None:
    """Test _load_toml raises SystemExit on invalid TOML format.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    file_path = tmp_path / "invalid.toml"
    file_path.write_text("[project\nname = 'foo'", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        manager._load_toml(path=file_path)
    assert exc_info.value.code == 1


def test_resolve_project_layout_standalone(temp_standalone_project: Path) -> None:
    """Test resolve_project_layout resolves standalone projects.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    layout = manager.resolve_project_layout(start=temp_standalone_project)
    assert not layout.is_workspace
    assert layout.root == temp_standalone_project
    assert layout.lock_path == temp_standalone_project / "uv.lock"
    assert not layout.workspace_members
    assert layout.hinted_member is None


def test_resolve_project_layout_workspace(temp_workspace_project: Path) -> None:
    """Test resolve_project_layout resolves uv workspace project.

    Args:
        temp_workspace_project (Path): Workspace root directory.
    """
    manager = UVDependencyManager(start_dir=temp_workspace_project)
    layout = manager.resolve_project_layout(start=temp_workspace_project)
    assert layout.is_workspace
    assert layout.root == temp_workspace_project
    assert len(layout.workspace_members) == 3  # Root plus 2 members
    assert layout.hinted_member is None


def test_resolve_project_layout_workspace_hinted(temp_workspace_project: Path) -> None:
    """Test resolve_project_layout resolves and hints a member directory.

    Args:
        temp_workspace_project (Path): Workspace root directory.
    """
    foo_dir = temp_workspace_project / "libs" / "foo"
    manager = UVDependencyManager(start_dir=foo_dir)
    layout = manager.resolve_project_layout(start=foo_dir)
    assert layout.is_workspace
    assert layout.root == temp_workspace_project
    assert layout.hinted_member is not None
    assert layout.hinted_member.name == "foo"
    assert layout.hinted_member.path == foo_dir


def test_resolve_project_layout_not_found(tmp_path: Path) -> None:
    """Test resolve_project_layout raises FileNotFoundError when no uv.lock is found.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    with pytest.raises(FileNotFoundError):
        manager.resolve_project_layout(start=tmp_path)


def test_bootstrap_missing_lock(
    temp_standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test bootstrap raises SystemExit when uv.lock is missing.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    mock_layout = ProjectLayout(
        root=temp_standalone_project,
        lock_path=temp_standalone_project / "nonexistent-uv.lock",
        workspace_members=[],
    )
    monkeypatch.setattr(manager, "resolve_project_layout", lambda start: mock_layout)
    args = argparse.Namespace(all_members=True, yes=True)
    with pytest.raises(SystemExit) as exc_info:
        manager.bootstrap(args=args)
    assert exc_info.value.code == 1


def test_bootstrap_no_workspace_members_selected(temp_workspace_project: Path) -> None:
    """Test bootstrap exits when workspace selection returns nothing.

    Args:
        temp_workspace_project (Path): Workspace root directory.
    """
    manager = UVDependencyManager(start_dir=temp_workspace_project)
    # Mock resolve_selected_members to return empty list
    manager.resolve_selected_members = lambda args: []  # type: ignore[assignment]
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        manager.bootstrap(args=args)
    assert exc_info.value.code == 1


def test_load_lock_versions(temp_standalone_project: Path) -> None:
    """Test load_lock_versions parses package versions.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.layout = manager.resolve_project_layout(start=temp_standalone_project)
    versions = manager.load_lock_versions()
    assert versions["requests"] == "2.28.1"
    assert versions["click"] == "8.1.3"


def test_load_direct_dependencies(temp_standalone_project: Path) -> None:
    """Test loading direct dependencies from a single pyproject.toml.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    pyproject_path = temp_standalone_project / "pyproject.toml"
    deps = manager.load_direct_dependencies(
        pyproject_path=pyproject_path, member_label="standalone"
    )
    # Check requests is loaded
    requests_dep = next(d for d in deps if d.name == "requests")
    assert requests_dep.requirement == "requests>=2.28.0"
    assert requests_dep.group == "project"
    assert requests_dep.pyproject_path == pyproject_path

    # Check dev dependency group
    pytest_dep = next(d for d in deps if d.name == "pytest")
    assert pytest_dep.requirement == "pytest>=7.0.0"
    assert pytest_dep.group == "dev"


def test_member_matches_token() -> None:
    """Test member_matches_token behavior."""
    manager = UVDependencyManager()
    member = WorkspaceMember(
        name="foo-bar",
        path=Path("/projects/foo-bar"),
        relative_path="libs/foo-bar",
    )
    assert manager.member_matches_token(member=member, token="foo-bar")
    assert manager.member_matches_token(member=member, token="FOO-BAR")
    assert manager.member_matches_token(member=member, token="libs/foo-bar")
    assert manager.member_matches_token(member=member, token="/projects/foo-bar")
    assert not manager.member_matches_token(member=member, token="foo")


def test_prompt_workspace_member_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test prompt_workspace_member_selection with various simulated inputs.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager()
    members = [
        WorkspaceMember(name="foo", path=Path("/foo"), relative_path="libs/foo"),
        WorkspaceMember(name="bar", path=Path("/bar"), relative_path="libs/bar"),
    ]

    # Empty input or 'q' returns empty list
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert (
        manager.prompt_workspace_member_selection(members=members, hinted_member=None)
        == []
    )

    monkeypatch.setattr("builtins.input", lambda _: "q")
    assert (
        manager.prompt_workspace_member_selection(members=members, hinted_member=None)
        == []
    )

    # 'all' returns all members
    monkeypatch.setattr("builtins.input", lambda _: "all")
    assert (
        manager.prompt_workspace_member_selection(members=members, hinted_member=None)
        == members
    )

    # Numbers selection (1-based index)
    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert manager.prompt_workspace_member_selection(
        members=members, hinted_member=None
    ) == [members[0]]

    # Comma-separated names & indices
    monkeypatch.setattr("builtins.input", lambda _: "1, bar")
    assert (
        manager.prompt_workspace_member_selection(members=members, hinted_member=None)
        == members
    )

    # Invalid values are ignored
    monkeypatch.setattr("builtins.input", lambda _: "99, invalid, 2")
    assert manager.prompt_workspace_member_selection(
        members=members, hinted_member=None
    ) == [members[1]]


def test_resolve_selected_members(
    temp_workspace_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test resolve_selected_members using CLI flags or prompt.

    Args:
        temp_workspace_project (Path): Workspace root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_workspace_project)
    manager.layout = manager.resolve_project_layout(start=temp_workspace_project)

    # --all-members flag
    args = argparse.Namespace(all_members=True, members=None, yes=False)
    assert len(manager.resolve_selected_members(args=args)) == 3

    # --members flag with valid names
    args = argparse.Namespace(all_members=False, members=["foo", "libs/bar"], yes=False)
    selected = manager.resolve_selected_members(args=args)
    assert len(selected) == 2
    assert {m.name for m in selected} == {"foo", "bar"}

    # --members flag with invalid name
    args = argparse.Namespace(all_members=False, members=["invalid"], yes=False)
    with pytest.raises(ValueError, match="Unknown workspace member: invalid"):
        manager.resolve_selected_members(args=args)

    # --yes flag (with hinted member)
    manager.layout = ProjectLayout(
        root=temp_workspace_project,
        lock_path=temp_workspace_project / "uv.lock",
        workspace_members=manager.layout.workspace_members,
        hinted_member=manager.layout.workspace_members[1],
    )
    args = argparse.Namespace(all_members=False, members=None, yes=True)
    assert manager.resolve_selected_members(args=args) == [
        manager.layout.workspace_members[1]
    ]

    # --yes flag (without hinted member)
    manager.layout = ProjectLayout(
        root=temp_workspace_project,
        lock_path=temp_workspace_project / "uv.lock",
        workspace_members=manager.layout.workspace_members,
        hinted_member=None,
    )
    assert (
        manager.resolve_selected_members(args=args) == manager.layout.workspace_members
    )

    # Interactive prompt fallback
    monkeypatch.setattr("builtins.input", lambda _: "all")
    args = argparse.Namespace(all_members=False, members=None, yes=False)
    assert (
        manager.resolve_selected_members(args=args) == manager.layout.workspace_members
    )


def test_run_uv_lock(
    temp_standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test run_uv_lock generates correct subprocess command and handles errors.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.layout = manager.resolve_project_layout(start=temp_standalone_project)

    captured_args: list[Any] = []

    def mock_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="Update requests v1 -> v2\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Test basic locks and flags
    manager.run_uv_lock(dry_run=True, upgrade_all=True, upgrade_packages=["click"])
    assert captured_args
    cmd = captured_args[0]
    assert cmd == ["uv", "lock", "--dry-run", "--upgrade", "--upgrade-package", "click"]

    # Test FileNotFoundError when uv is missing
    def mock_run_missing(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", mock_run_missing)
    with pytest.raises(SystemExit) as exc_info:
        manager.run_uv_lock(dry_run=False, upgrade_all=False, upgrade_packages=[])
    assert exc_info.value.code == 1


def test_parse_upgrade_lines() -> None:
    """Test parsing of uv lock output lines."""
    manager = UVDependencyManager()
    output = """
    Resolved 12 packages
    Update requests v2.28.0 -> v2.29.0
    Update click v8.1.0 -> v8.1.3
    Some other status message
    """
    updates = manager.parse_upgrade_lines(output=output)
    assert len(updates) == 2
    assert updates[0] == PackageUpdate(
        name="requests", current="2.28.0", latest="2.29.0"
    )
    assert updates[1] == PackageUpdate(name="click", current="8.1.0", latest="8.1.3")


def test_discover_updates(
    temp_standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test discover_updates executes dry-runs and parses output correctly.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.layout = manager.resolve_project_layout(start=temp_standalone_project)

    # Success case
    def mock_run_success(
        dry_run: bool, upgrade_all: bool, upgrade_packages: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Update requests v2.28.0 -> v2.29.0",
            stderr="",
        )

    monkeypatch.setattr(manager, "run_uv_lock", mock_run_success)
    updates = manager.discover_updates(upgrade_packages=["requests"])
    assert len(updates) == 1
    assert updates[0].name == "requests"

    # Failure case
    def mock_run_fail(
        dry_run: bool, upgrade_all: bool, upgrade_packages: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Could not resolve dependencies",
        )

    monkeypatch.setattr(manager, "run_uv_lock", mock_run_fail)
    with pytest.raises(
        RuntimeError, match="uv lock --dry-run failed: Could not resolve dependencies"
    ):
        manager.discover_updates()


def test_format_role(temp_standalone_project: Path) -> None:
    """Test formatting package role (direct vs transitive).

    Args:
        temp_standalone_project (Path): Standalone project root directory.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.bootstrap(args=argparse.Namespace(all_members=True, yes=True))

    assert manager.format_role(package_name="requests") == "direct (standalone/project)"
    assert manager.format_role(package_name="pytest") == "direct (standalone/dev)"
    assert manager.format_role(package_name="transitive-pkg") == "transitive"


def test_print_update_table(
    temp_standalone_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test printing update tables prints the title and packages correctly.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.bootstrap(args=argparse.Namespace(all_members=True, yes=True))

    updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]
    manager.print_update_table(updates=updates, title="Title Here")
    captured = capsys.readouterr()
    assert "Title Here" in captured.out
    assert "requests" in captured.out
    assert "2.28.0" in captured.out
    assert "2.29.0" in captured.out

    # Empty case
    manager.print_update_table(updates=[], title="Empty Title")
    captured = capsys.readouterr()
    assert "Empty Title: none" in captured.out


def test_prompt_package_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test prompt_package_selection options.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager()
    updates = [
        PackageUpdate(name="foo", current="1.0", latest="1.1"),
        PackageUpdate(name="bar", current="2.0", latest="2.1"),
    ]

    monkeypatch.setattr("builtins.input", lambda _: "all")
    assert manager.prompt_package_selection(updates=updates) == ["foo", "bar"]

    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert manager.prompt_package_selection(updates=updates) == ["foo"]

    monkeypatch.setattr("builtins.input", lambda _: "1, bar")
    assert manager.prompt_package_selection(updates=updates) == ["bar", "foo"]

    monkeypatch.setattr("builtins.input", lambda _: "q")
    assert manager.prompt_package_selection(updates=updates) == []


def test_pinned_requirement() -> None:
    """Test pinned_requirement logic."""
    manager = UVDependencyManager()
    dep = DirectDependency(
        name="foo",
        requirement="foo[extra]>=1.0 ; python_version >= '3.10'",
        group="project",
        member_label="member",
        pyproject_path=Path("/foo"),
    )
    pin = manager.pinned_requirement(dep=dep, version="1.2.3")
    assert pin in (
        "foo[extra]==1.2.3 ; python_version >= '3.10'",
        'foo[extra]==1.2.3 ; python_version >= "3.10"',
    )


def test_apply_pyproject_pins(tmp_path: Path) -> None:
    """Test applying pyproject pins rewrite constraints to pyproject.toml.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """[project]
dependencies = [
    "requests>=2.28.0",
    "click>=8.0",
]
""",
        encoding="utf-8",
    )

    dep1 = DirectDependency(
        name="requests",
        requirement="requests>=2.28.0",
        group="project",
        member_label="test",
        pyproject_path=pyproject_path,
    )
    dep2 = DirectDependency(
        name="click",
        requirement="click>=8.0",
        group="project",
        member_label="test",
        pyproject_path=pyproject_path,
    )

    lock_versions = {"requests": "2.29.0", "click": "8.1.3"}

    # Pin only requests
    applied = manager.apply_pyproject_pins(
        pyproject_path=pyproject_path,
        lock_versions=lock_versions,
        deps=[dep1, dep2],
        pin_names=["requests"],
        member_label="test",
    )
    assert len(applied) == 1
    assert applied[0] == ("test", "project", "requests", "requests==2.29.0")

    content = pyproject_path.read_text(encoding="utf-8")
    assert '"requests==2.29.0"' in content
    assert '"click>=8.0"' in content


def test_run_uv_sync(
    temp_standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test run_uv_sync handles successful subprocess, missing uv, and subprocess error.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.layout = manager.resolve_project_layout(start=temp_standalone_project)

    # Success case
    def mock_run_success(
        args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", mock_run_success)
    manager.run_uv_sync()  # Should not raise

    # Missing uv
    def mock_run_missing(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", mock_run_missing)
    with pytest.raises(SystemExit) as exc_info:
        manager.run_uv_sync()
    assert exc_info.value.code == 1

    # Sync fail
    def mock_run_fail(
        args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout="", stderr="Sync error"
        )

    monkeypatch.setattr(subprocess, "run", mock_run_fail)
    with pytest.raises(RuntimeError, match="uv sync failed: Sync error"):
        manager.run_uv_sync()


def test_load_direct_dependencies_with_url(tmp_path: Path) -> None:
    """Test load_direct_dependencies ignores dependencies with URL specifications.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """[project]
dependencies = [
    "requests @ https://github.com/psf/requests/archive/refs/heads/main.zip",
]
[dependency-groups]
dev = [
    "pytest @ https://github.com/pytest-dev/pytest/archive/refs/heads/main.zip",
]
""",
        encoding="utf-8",
    )
    deps = manager.load_direct_dependencies(
        pyproject_path=pyproject_path, member_label="test"
    )
    assert not deps


def test_discover_workspace_members_edge_cases(tmp_path: Path) -> None:
    """Test discover_workspace_members ignores directories without pyproject.toml and duplicate members.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    root = tmp_path / "workspace"
    root.mkdir()
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        """[tool.uv.workspace]
members = ["libs/foo", "libs/bar", "libs/foo"]
""",
        encoding="utf-8",
    )
    foo_dir = root / "libs" / "foo"
    foo_dir.mkdir(parents=True)
    (foo_dir / "pyproject.toml").write_text("[project]\nname='foo'", encoding="utf-8")

    bar_dir = root / "libs" / "bar"
    bar_dir.mkdir(parents=True)

    members = manager.discover_workspace_members(workspace_root=root)
    assert len(members) == 2
    assert {m.name for m in members} == {".", "foo"}


def test_bootstrap_value_error(temp_workspace_project: Path) -> None:
    """Test bootstrap raises SystemExit when resolve_selected_members raises ValueError.

    Args:
        temp_workspace_project (Path): Workspace root directory.
    """
    manager = UVDependencyManager(start_dir=temp_workspace_project)

    def raise_value_error(args: Any) -> Any:
        raise ValueError("Mocked error")

    manager.resolve_selected_members = raise_value_error  # type: ignore[assignment]

    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        manager.bootstrap(args=args)
    assert exc_info.value.code == 1


def test_prompt_workspace_member_selection_edge_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test edge cases in prompt_workspace_member_selection.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager()
    assert (
        manager.prompt_workspace_member_selection(members=[], hinted_member=None) == []
    )

    members = [
        WorkspaceMember(name="foo", path=Path("/foo"), relative_path="libs/foo"),
    ]
    monkeypatch.setattr("builtins.input", lambda _: ", , 1, 1")
    selected = manager.prompt_workspace_member_selection(
        members=members, hinted_member=members[0]
    )
    assert selected == members


def test_resolve_selected_members_edge_cases(
    temp_workspace_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test resolve_selected_members with duplicate flags and empty selections.

    Args:
        temp_workspace_project (Path): Workspace root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_workspace_project)
    manager.layout = manager.resolve_project_layout(start=temp_workspace_project)

    args = argparse.Namespace(all_members=False, members=["foo", "foo"], yes=False)
    selected = manager.resolve_selected_members(args=args)
    assert len(selected) == 1
    assert selected[0].name == "foo"

    monkeypatch.setattr("builtins.input", lambda _: "")
    args_interactive = argparse.Namespace(all_members=False, members=None, yes=False)
    assert manager.resolve_selected_members(args=args_interactive) == []


def test_prompt_package_selection_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test prompt_package_selection with empty updates or empty choice tokens.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager()
    assert manager.prompt_package_selection(updates=[]) == []

    updates = [PackageUpdate(name="foo", current="1.0", latest="1.1")]
    monkeypatch.setattr("builtins.input", lambda _: ", , 1")
    assert manager.prompt_package_selection(updates=updates) == ["foo"]


def test_apply_pyproject_pins_edge_cases(tmp_path: Path) -> None:
    """Test apply_pyproject_pins when version is missing or target is already pinned.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """[project]
dependencies = [
    "requests==2.29.0",
]
""",
        encoding="utf-8",
    )
    dep = DirectDependency(
        name="requests",
        requirement="requests==2.29.0",
        group="project",
        member_label="test",
        pyproject_path=pyproject_path,
    )

    applied1 = manager.apply_pyproject_pins(
        pyproject_path=pyproject_path,
        lock_versions={},
        deps=[dep],
        pin_names=["requests"],
        member_label="test",
    )
    assert not applied1

    applied2 = manager.apply_pyproject_pins(
        pyproject_path=pyproject_path,
        lock_versions={"requests": "2.29.0"},
        deps=[dep],
        pin_names=["requests"],
        member_label="test",
    )
    assert not applied2


def test_apply_all_pyproject_pins(tmp_path: Path) -> None:
    """Test apply_all_pyproject_pins pins dependencies across packages.

    Args:
        tmp_path (Path): pytest tmp_path fixture.
    """
    manager = UVDependencyManager()
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """[project]
dependencies = [
    "requests>=2.28.0",
]
""",
        encoding="utf-8",
    )
    dep = DirectDependency(
        name="requests",
        requirement="requests>=2.28.0",
        group="project",
        member_label="test",
        pyproject_path=pyproject_path,
    )
    manager.direct_deps = {"requests": [dep]}

    applied = manager.apply_all_pyproject_pins(
        lock_versions={"requests": "2.29.0"},
        pin_names=["requests"],
    )
    assert len(applied) == 1
    assert applied[0] == ("test", "project", "requests", "requests==2.29.0")


def test_workspace_load_and_summary(
    temp_workspace_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test bootstrap, direct dependency load, and layout summary printing for a workspace.

    Args:
        temp_workspace_project (Path): Workspace root directory.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    manager = UVDependencyManager(start_dir=temp_workspace_project)
    args = argparse.Namespace(all_members=True, yes=True)
    manager.bootstrap(args=args)

    assert "requests" in manager.direct_deps
    assert "click" in manager.direct_deps

    lock_versions = manager.load_lock_versions()
    manager.print_layout_summary(lock_versions=lock_versions)
    captured = capsys.readouterr()
    assert "Workspace:" in captured.out
    assert "Members:" in captured.out


def test_standalone_layout_summary(
    temp_standalone_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test print_layout_summary for a standalone project.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    args = argparse.Namespace(all_members=True, yes=True)
    manager.bootstrap(args=args)

    lock_versions = manager.load_lock_versions()
    manager.print_layout_summary(lock_versions=lock_versions)
    captured = capsys.readouterr()
    assert "Project:" in captured.out
    assert "Locked packages:" in captured.out


def test_run_uv_tree_outdated(
    temp_standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test run_uv_tree_outdated success and missing uv executable scenarios.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.layout = manager.resolve_project_layout(start=temp_standalone_project)

    # Success scenario
    def mock_run_success(
        args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="success", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", mock_run_success)
    res = manager.run_uv_tree_outdated()
    assert res.returncode == 0
    assert res.stdout == "success"

    # Missing uv executable
    def mock_run_missing(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", mock_run_missing)
    with pytest.raises(SystemExit) as exc_info:
        manager.run_uv_tree_outdated()
    assert exc_info.value.code == 1


def test_parse_tree_outdated_lines() -> None:
    """Test parse_tree_outdated_lines correct detection and fields matching."""
    manager = UVDependencyManager()
    output = """
    uvu v0.1.0
    ├── requests v2.28.0 (latest: v2.34.2)
    └── urllib3 v1.26.20 (latest: v2.7.0)
    """
    updates = manager.parse_tree_outdated_lines(output=output)
    assert len(updates) == 2
    assert updates[0] == PackageUpdate(
        name="requests", current="2.28.0", latest="2.34.2"
    )
    assert updates[1] == PackageUpdate(
        name="urllib3", current="1.26.20", latest="2.7.0"
    )


def test_discover_blocked_updates(
    temp_standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test discover_blocked_updates diffs compatible updates correctly.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.layout = manager.resolve_project_layout(start=temp_standalone_project)

    # Mock uv tree --outdated output containing requests (blocked) and urllib3 (compatible)
    def mock_run(self) -> subprocess.CompletedProcess[str]:
        output = """
        ├── requests v2.28.0 (latest: v2.34.2)
        └── urllib3 v1.26.20 (latest: v2.7.0)
        """
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output, stderr=""
        )

    monkeypatch.setattr(UVDependencyManager, "run_uv_tree_outdated", mock_run)

    # urllib3 is compatible, requests is blocked by constraints
    compatible = [PackageUpdate(name="urllib3", current="1.26.20", latest="2.7.0")]
    blocked = manager.discover_blocked_updates(compatible_updates=compatible)
    assert len(blocked) == 1
    assert blocked[0].name == "requests"

    # Check failure code exit
    def mock_run_fail(self) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Error"
        )

    monkeypatch.setattr(UVDependencyManager, "run_uv_tree_outdated", mock_run_fail)
    assert manager.discover_blocked_updates(compatible_updates=[]) == []


def test_load_reverse_dependency_map(temp_workspace_project: Path) -> None:
    """Test load_reverse_dependency_map generates correct reverse dependency mapping.

    Args:
        temp_workspace_project (Path): Workspace root directory.
    """
    manager = UVDependencyManager(start_dir=temp_workspace_project)
    manager.layout = manager.resolve_project_layout(start=temp_workspace_project)

    reverse_map = manager.load_reverse_dependency_map()
    assert reverse_map["requests"] == ["foo"]
    assert reverse_map["click"] == ["bar"]

    # Test error handling when lockfile or layout is missing
    manager_no_layout = UVDependencyManager()
    assert manager_no_layout.load_reverse_dependency_map() == {}


def test_get_blocker_description(temp_standalone_project: Path) -> None:
    """Test get_blocker_description correctly formats direct constraints and transitive parents.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.bootstrap(args=argparse.Namespace(all_members=True, yes=True))

    # requests is a direct dependency
    desc_direct = manager.get_blocker_description(
        package_name="requests", reverse_map={}
    )
    assert "pyproject.toml" in desc_direct
    assert "requests>=2.28.0" in desc_direct

    # transitive package
    desc_transitive = manager.get_blocker_description(
        package_name="some-pkg", reverse_map={"some-pkg": ["parent-a", "parent-b"]}
    )
    assert desc_transitive == "required by parent-a, parent-b"

    # unknown package
    desc_unknown = manager.get_blocker_description(
        package_name="unknown-pkg", reverse_map={}
    )
    assert desc_unknown == "unknown constraint"


def test_load_reverse_dependency_map_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test load_reverse_dependency_map exception handling and string parsing."""
    manager = UVDependencyManager()
    manager.layout = ProjectLayout(
        root=Path("/dummy"),
        lock_path=Path("/dummy/uv.lock"),
        workspace_members=[],
        hinted_member=None,
    )

    # 1. Test invalid TOML exception
    def mock_load_toml_fail(*args: Any, **kwargs: Any) -> Any:
        raise Exception("Invalid TOML")

    monkeypatch.setattr(manager, "_load_toml", mock_load_toml_fail)
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    assert manager.load_reverse_dependency_map() == {}

    # 2. Test string dependency parsing and exception fallback
    mock_data = {
        "package": [
            {
                "name": "foo",
                "dependencies": [
                    "requests>=2.0.0",
                    "invalid-specifier!!!",
                ],
            }
        ]
    }

    def mock_load_toml_ok(*args: Any, **kwargs: Any) -> Any:
        return mock_data

    manager2 = UVDependencyManager()
    manager2.layout = manager.layout
    monkeypatch.setattr(manager2, "_load_toml", mock_load_toml_ok)
    rev_map = manager2.load_reverse_dependency_map()
    assert "requests" in rev_map
    assert rev_map["requests"] == ["foo"]
    assert "invalid-specifier!!!" in rev_map
    assert rev_map["invalid-specifier!!!"] == ["foo"]


def test_print_update_table_show_blocked_by(
    temp_standalone_project: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test print_update_table with show_blocked_by=True.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.bootstrap(args=argparse.Namespace(all_members=True, yes=True))

    updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]

    # Mock load_reverse_dependency_map to return some mapping
    monkeypatch.setattr(
        manager, "load_reverse_dependency_map", lambda: {"requests": ["foo"]}
    )

    manager.print_update_table(
        updates=updates, title="Blocked Table", show_blocked_by=True
    )
    captured = capsys.readouterr()
    assert "blocked by" in captured.out
    assert "pyproject.toml" in captured.out


def test_discover_updates_with_outdated_direct_deps(
    temp_standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test discover_updates includes outdated direct dependencies.

    Args:
        temp_standalone_project (Path): Standalone project root directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    manager = UVDependencyManager(start_dir=temp_standalone_project)
    manager.bootstrap(args=argparse.Namespace(all_members=True, yes=True))

    # Mock uv lock --dry-run to return compatible updates (e.g. click)
    def mock_run_uv_lock(
        self, *, dry_run: bool, upgrade_all: bool, upgrade_packages: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        if upgrade_all or "click" in upgrade_packages:
            output = "Update click v8.1.3 -> v8.2.0"
        else:
            output = ""
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output, stderr=""
        )

    # Mock uv tree --outdated output containing requests (direct but blocked by constraint)
    # and urllib3 (transitive, not in direct deps)
    def mock_run_tree(self) -> subprocess.CompletedProcess[str]:
        output = """
        ├── requests v2.28.0 (latest: v2.34.2)
        └── urllib3 v1.26.20 (latest: v2.7.0)
        """
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output, stderr=""
        )

    monkeypatch.setattr(UVDependencyManager, "run_uv_lock", mock_run_uv_lock)
    monkeypatch.setattr(UVDependencyManager, "run_uv_tree_outdated", mock_run_tree)

    # Check with upgrade_packages=None (all dependencies)
    # click (compatible) and requests (outdated direct dependency) should be in the list
    # urllib3 (transitive) should NOT be in the list
    updates = manager.discover_updates()
    names = {u.name for u in updates}
    assert "click" in names
    assert "requests" in names
    assert "urllib3" not in names

    # Check with upgrade_packages filtering for requests
    updates_requests = manager.discover_updates(upgrade_packages=["requests"])
    names_requests = {u.name for u in updates_requests}
    assert "requests" in names_requests
    assert "click" not in names_requests


def test_core_facade() -> None:
    """Test that core.py facade re-exports all classes correctly."""
    import update_uv_packages.core as core

    assert core.DirectDependency is DirectDependency
    assert core.PackageUpdate is PackageUpdate
    assert core.ProjectLayout is ProjectLayout
    assert core.UpdateReport is UpdateReport
    assert core.UVDependencyManager is UVDependencyManager
    assert core.WorkspaceMember is WorkspaceMember
