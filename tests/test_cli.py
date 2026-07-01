"""Unit tests for cli.py."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any
import pytest

from update_uv_packages.cli import (
    build_parser,
    cmd_check,
    cmd_update,
    main,
    print_report,
)
from update_uv_packages.package_update import PackageUpdate
from update_uv_packages.update_report import UpdateReport


def test_print_report_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """Test print_report with no changes.

    Args:
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    # Create an empty update report
    report = UpdateReport(lock_updates=[], pyproject_pins=[])

    # Run the report generator
    print_report(report=report)

    # Assert that stdout shows that nothing changed in the lockfile
    captured = capsys.readouterr()
    assert "No lockfile version changes." in captured.out


def test_print_report_with_changes(capsys: pytest.CaptureFixture[str]) -> None:
    """Test print_report displaying lock updates and pyproject pins.

    Args:
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    # Create a report with a mock package bump and a pyproject file pin
    report = UpdateReport(
        lock_updates=[PackageUpdate(name="requests", current="1.0.0", latest="2.0.0")],
        pyproject_pins=[("member-a", "project", "requests", "requests==2.0.0")],
    )

    # Run the report generator
    print_report(report=report)

    # Verify that both the lock updates table and the pin details are printed in stdout
    captured = capsys.readouterr()
    assert "requests" in captured.out
    assert "1.0.0" in captured.out
    assert "2.0.0" in captured.out
    assert "member-a" in captured.out
    assert "requests==2.0.0" in captured.out


def test_build_parser() -> None:
    """Test building parser and command detection."""
    # Build the argparse parser
    parser = build_parser()

    # Test that project directory global flag and command keyword are parsed correctly
    args = parser.parse_args(["--project-dir", "/tmp", "check"])
    assert args.project_dir == Path("/tmp")
    assert args.command == "check"

    # Test parser settings for the check subcommand flags
    args = parser.parse_args(["check", "--verbose", "--all-members"])
    assert args.verbose is True
    assert args.all_members is True

    # Test parser settings for the update subcommand flags
    args = parser.parse_args(["update", "--all", "--pin-updated", "--sync"])
    assert args.all is True
    assert args.pin_updated is True
    assert args.sync is True


def test_cmd_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_check prints expected info.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    # Define mock versions and updates to be returned by mock manager
    mock_lock_versions = {"requests": "2.28.0", "click": "8.1.0"}
    mock_updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]

    # Stub UVDependencyManager to isolate CLI command logic
    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            pass

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            return mock_lock_versions

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(self, compatible_updates: Any) -> list[Any]:
            return []

        def print_layout_summary(self, lock_versions: Any) -> None:
            print("Layout Summary")

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            print(f"{title}: requests 2.28.0 -> 2.29.0")

        def format_role(self, package_name: str) -> str:
            return "direct"

    # Monkeypatch the real UVDependencyManager with our mock
    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    # Run check subcommand with verbose flag
    args = argparse.Namespace(
        project_dir=None, verbose=True, all_members=True, yes=True
    )
    code = cmd_check(args=args)
    assert code == 0

    captured = capsys.readouterr()
    assert "Layout Summary" in captured.out
    assert "Available compatible updates" in captured.out
    assert "Up to date" in captured.out
    assert "click==8.1.0" in captured.out


def test_cmd_update_no_updates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_update exits early when there is nothing to update.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            pass

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            return {}

        def discover_updates(self) -> list[PackageUpdate]:
            return []

        def discover_blocked_updates(self, compatible_updates: Any) -> list[Any]:
            return []

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    args = argparse.Namespace(
        project_dir=None,
        packages=None,
        all=False,
        yes=False,
        pin_all=False,
        pin_updated=False,
        sync=False,
    )
    code = cmd_update(args=args)
    assert code == 0
    captured = capsys.readouterr()
    assert "Nothing to update." in captured.out


def test_cmd_update_lock_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_update returns error code when uv lock fails.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    mock_lock_versions = {"requests": "2.28.0"}
    mock_updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            self.direct_deps: dict[str, Any] = {}

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            return mock_lock_versions

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(self, compatible_updates: Any) -> list[Any]:
            return []

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            pass

        def normalize_name(self, name: str) -> str:
            return name

        def run_uv_lock(
            self, dry_run: bool, upgrade_all: bool, upgrade_packages: Any
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="Upgrade failed"
            )

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    args = argparse.Namespace(
        project_dir=None,
        packages=["requests"],
        all=False,
        yes=True,
        pin_all=False,
        pin_updated=False,
        sync=False,
    )
    code = cmd_update(args=args)
    assert code == 1
    captured = capsys.readouterr()
    assert "Upgrade failed" in captured.err


def test_cmd_update_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_update successfully updates packages and applies pins.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    mock_before_lock = {"requests": "2.28.0", "click": "8.1.0"}
    mock_after_lock = {"requests": "2.29.0", "click": "8.1.0"}
    mock_updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            self.direct_deps = {"requests": []}
            self.selected_packages: list[str] = []

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            # Simulate lock version update when run_uv_lock is called
            if hasattr(self, "_locked"):
                return mock_after_lock
            return mock_before_lock

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(self, compatible_updates: Any) -> list[Any]:
            return []

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            pass

        def normalize_name(self, name: str) -> str:
            return name

        def run_uv_lock(
            self, dry_run: bool, upgrade_all: bool, upgrade_packages: Any
        ) -> subprocess.CompletedProcess[str]:
            self._locked = True
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Success stdout", stderr=""
            )

        def apply_all_pyproject_pins(
            self, lock_versions: Any, pin_names: Any
        ) -> list[Any]:
            return [("standalone", "project", "requests", "requests==2.29.0")]

        def run_uv_sync(self) -> None:
            print("uv sync output")

        def prompt_package_selection(self, updates: Any) -> list[str]:
            return self.selected_packages

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    # Use prompt fallback (simulating empty choice -> returns empty list)
    args = argparse.Namespace(
        project_dir=None,
        packages=None,
        all=False,
        yes=False,
        pin_all=False,
        pin_updated=False,
        sync=False,
    )
    code = cmd_update(args=args)
    assert code == 0
    captured = capsys.readouterr()
    assert "No packages selected." in captured.out

    # Execute with packages and pin_updated
    args_with_pkgs = argparse.Namespace(
        project_dir=None,
        packages=None,
        all=True,
        yes=True,
        pin_all=False,
        pin_updated=True,
        sync=True,
    )
    code2 = cmd_update(args=args_with_pkgs)
    assert code2 == 0
    captured2 = capsys.readouterr()
    assert "Success stdout" in captured2.out
    assert "requests==2.29.0" in captured2.out
    assert "uv sync output" in captured2.out


def test_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test main parses options and executes subcommand runner.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
    """
    called_args: list[Any] = []

    def mock_cmd_check(args: Any) -> int:
        called_args.append(args)
        return 42

    monkeypatch.setattr("update_uv_packages.cli.cmd_check", mock_cmd_check)

    code = main(["check", "--verbose"])
    assert code == 42
    assert len(called_args) == 1
    assert called_args[0].verbose is True


def test_cmd_update_yes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_update handles the yes flag without all or packages specified.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    mock_before_lock = {"requests": "2.28.0"}
    mock_after_lock = {"requests": "2.29.0"}
    mock_updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            self.direct_deps = {"requests": []}

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            if hasattr(self, "_locked"):
                return mock_after_lock
            return mock_before_lock

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(self, compatible_updates: Any) -> list[Any]:
            return []

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            pass

        def normalize_name(self, name: str) -> str:
            return name

        def run_uv_lock(
            self, dry_run: bool, upgrade_all: bool, upgrade_packages: Any
        ) -> subprocess.CompletedProcess[str]:
            self._locked = True
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Success stdout", stderr=""
            )

        def apply_all_pyproject_pins(
            self, lock_versions: Any, pin_names: Any
        ) -> list[Any]:
            return []

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    args = argparse.Namespace(
        project_dir=None,
        packages=None,
        all=False,
        yes=True,
        pin_all=False,
        pin_updated=False,
        sync=False,
    )
    code = cmd_update(args=args)
    assert code == 0


def test_cmd_update_pin_all(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_update with pin_all flag set to True.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    mock_before_lock = {"requests": "2.28.0"}
    mock_after_lock = {"requests": "2.29.0"}
    mock_updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            self.direct_deps = {"requests": []}

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            if hasattr(self, "_locked"):
                return mock_after_lock
            return mock_before_lock

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(self, compatible_updates: Any) -> list[Any]:
            return []

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            pass

        def normalize_name(self, name: str) -> str:
            return name

        def run_uv_lock(
            self, dry_run: bool, upgrade_all: bool, upgrade_packages: Any
        ) -> subprocess.CompletedProcess[str]:
            self._locked = True
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Success stdout", stderr=""
            )

        def apply_all_pyproject_pins(
            self, lock_versions: Any, pin_names: Any
        ) -> list[Any]:
            return [("standalone", "project", "requests", "requests==2.29.0")]

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    args = argparse.Namespace(
        project_dir=None,
        packages=None,
        all=True,
        yes=True,
        pin_all=True,
        pin_updated=False,
        sync=False,
    )
    code = cmd_update(args=args)
    assert code == 0
    captured = capsys.readouterr()
    assert "requests==2.29.0" in captured.out


def test_cmd_check_with_blocked_updates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_check displays blocked outdated packages in stdout.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    mock_lock_versions = {"requests": "2.28.0"}
    mock_updates = []
    mock_blocked = [PackageUpdate(name="requests", current="2.28.0", latest="2.34.2")]

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            pass

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            return mock_lock_versions

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(
            self, compatible_updates: Any
        ) -> list[PackageUpdate]:
            return mock_blocked

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            print(f"{title}: requests 2.28.0 -> 2.34.2")

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    args = argparse.Namespace(
        project_dir=None, verbose=False, all_members=True, yes=True
    )
    code = cmd_check(args=args)
    assert code == 0

    captured = capsys.readouterr()
    assert "blocked by constraints" in captured.out
    assert "requests 2.28.0 -> 2.34.2" in captured.out


def test_cmd_update_with_blocked_updates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_update displaying blocked outdated packages warnings.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    mock_before_lock = {"requests": "2.28.0"}
    mock_after_lock = {"requests": "2.29.0"}
    mock_updates = [PackageUpdate(name="requests", current="2.28.0", latest="2.29.0")]
    mock_blocked = [PackageUpdate(name="urllib3", current="1.26.20", latest="2.7.0")]

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            self.direct_deps = {"requests": []}
            self.selected_packages = ["requests"]

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            if hasattr(self, "_locked"):
                return mock_after_lock
            return mock_before_lock

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(
            self, compatible_updates: Any
        ) -> list[PackageUpdate]:
            return mock_blocked

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            print(
                f"{title}: requests 2.28.0 -> 2.29.0"
                if "compatible" in title
                else f"{title}: urllib3 1.26.20 -> 2.7.0"
            )

        def normalize_name(self, name: str) -> str:
            return name

        def run_uv_lock(
            self, dry_run: bool, upgrade_all: bool, upgrade_packages: Any
        ) -> subprocess.CompletedProcess[str]:
            self._locked = True
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Success stdout", stderr=""
            )

        def apply_all_pyproject_pins(
            self, lock_versions: Any, pin_names: Any
        ) -> list[Any]:
            return []

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    args = argparse.Namespace(
        project_dir=None,
        packages=None,
        all=True,
        yes=True,
        pin_all=False,
        pin_updated=False,
        sync=False,
    )
    code = cmd_update(args=args)
    assert code == 0
    captured = capsys.readouterr()
    assert "blocked by constraints" in captured.out
    assert "urllib3 1.26.20 -> 2.7.0" in captured.out


def test_cmd_update_with_blocking_constraints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test cmd_update pre-pinning of direct dependencies with blocking constraints.

    Args:
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.
        capsys (pytest.CaptureFixture[str]): pytest capsys fixture.
    """
    mock_before_lock = {"requests": "2.28.0", "click": "8.0.0", "urllib3": "1.26.0"}
    mock_after_lock = {"requests": "2.29.0", "click": "8.1.0", "urllib3": "1.27.0"}

    mock_updates = [
        PackageUpdate(name="requests", current="2.28.0", latest="2.29.0"),
        PackageUpdate(name="click", current="8.0.0", latest="8.1.0"),
        PackageUpdate(name="urllib3", current="1.26.0", latest="1.27.0"),
    ]

    class MockDep:
        def __init__(self, requirement: str) -> None:
            self.requirement = requirement

    mock_direct_deps = {
        "requests": [MockDep("requests==2.28.0")],
        "click": [MockDep("click>=8.0.0")],
        "urllib3": [MockDep("invalid!!!requirement")],
        "noupdate": [MockDep("noupdate==1.0.0")],
    }

    class MockManager:
        def __init__(self, start_dir: Any = None) -> None:
            self.direct_deps = mock_direct_deps

        def bootstrap(self, args: Any) -> None:
            pass

        def load_lock_versions(self) -> dict[str, str]:
            if hasattr(self, "_locked"):
                return mock_after_lock
            return mock_before_lock

        def discover_updates(self) -> list[PackageUpdate]:
            return mock_updates

        def discover_blocked_updates(
            self, compatible_updates: Any
        ) -> list[PackageUpdate]:
            return []

        def print_layout_summary(self, lock_versions: Any) -> None:
            pass

        def print_update_table(self, updates: Any, title: str, **kwargs: Any) -> None:
            pass

        def normalize_name(self, name: str) -> str:
            return name

        def run_uv_lock(
            self, dry_run: bool, upgrade_all: bool, upgrade_packages: Any
        ) -> subprocess.CompletedProcess[str]:
            self._locked = True
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="Success", stderr=""
            )

        def apply_all_pyproject_pins(
            self, lock_versions: Any, pin_names: Any
        ) -> list[Any]:
            pins = []
            for name in pin_names:
                pins.append(
                    ("member-a", "project", name, f"{name}=={lock_versions[name]}")
                )
            return pins

        def load_layout_direct_dependencies(self) -> dict[str, list[Any]]:
            return mock_direct_deps

    monkeypatch.setattr("update_uv_packages.cli.UVDependencyManager", MockManager)

    # Run update subcommand with packages=[requests, click, urllib3, noupdate, nonexistent]
    args = argparse.Namespace(
        project_dir=None,
        packages=["requests", "click", "urllib3", "noupdate", "nonexistent"],
        all=False,
        yes=True,
        pin_all=False,
        pin_updated=False,
        sync=False,
    )
    code = cmd_update(args=args)
    assert code == 0
    captured = capsys.readouterr()

    # Split output to only examine the pyproject.toml pins section
    parts = captured.out.split("pyproject.toml pins")
    assert len(parts) == 2
    pins_section = parts[1]

    # requests and urllib3 should be pre-pinned
    assert "requests" in pins_section
    assert "urllib3" in pins_section
    # click and noupdate should not be pre-pinned
    assert "click" not in pins_section
    assert "noupdate" not in pins_section
