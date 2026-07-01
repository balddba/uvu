"""Fixtures and test setup configuration for pytest."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def temp_standalone_project(tmp_path: Path) -> Path:
    """Create a temporary standalone project layout with pyproject.toml and uv.lock.

    Args:
        tmp_path (Path): pytest tmp_path fixture.

    Returns:
        Path: Path to the root of the created project.
    """
    # Create the standalone project root folder
    root = tmp_path / "standalone_project"
    root.mkdir()

    # Write a pyproject.toml simulating a basic project with standard dependencies
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "standalone"
version = "1.0.0"
dependencies = [
    "requests>=2.28.0",
    "click>=8.0",
]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
]
""",
        encoding="utf-8",
    )

    # Write a uv.lock containing locked package metadata matching the pyproject
    lock = root / "uv.lock"
    lock.write_text(
        """version = 1
revision = 1

[[package]]
name = "requests"
version = "2.28.1"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://..." }

[[package]]
name = "click"
version = "8.1.3"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://..." }

[[package]]
name = "pytest"
version = "7.2.0"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://..." }
""",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def temp_workspace_project(tmp_path: Path) -> Path:
    """Create a temporary workspace layout with multiple members.

    Args:
        tmp_path (Path): pytest tmp_path fixture.

    Returns:
        Path: Path to the root of the created workspace.
    """
    # Create the workspace root folder
    root = tmp_path / "workspace_project"
    root.mkdir()

    # Write root pyproject.toml specifying workspace member folders
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        """[project]
name = "workspace-root"
version = "0.1.0"
dependencies = []

[tool.uv.workspace]
members = ["libs/foo", "libs/bar"]
""",
        encoding="utf-8",
    )

    # Write root uv.lock containing resolved dependencies for all members
    lock = root / "uv.lock"
    lock.write_text(
        """version = 1
revision = 1

[[package]]
name = "foo"
version = "0.1.0"
dependencies = [
    { name = "requests" }
]

[[package]]
name = "bar"
version = "0.2.0"
dependencies = [
    { name = "click" }
]

[[package]]
name = "requests"
version = "2.28.0"

[[package]]
name = "click"
version = "8.1.0"
""",
        encoding="utf-8",
    )

    # Setup the first workspace member folder: libs/foo
    foo_dir = root / "libs" / "foo"
    foo_dir.mkdir(parents=True)
    foo_pyproject = foo_dir / "pyproject.toml"
    foo_pyproject.write_text(
        """[project]
name = "foo"
version = "0.1.0"
dependencies = [
    "requests>=2.0.0",
]
""",
        encoding="utf-8",
    )

    # Setup the second workspace member folder: libs/bar
    bar_dir = root / "libs" / "bar"
    bar_dir.mkdir(parents=True)
    bar_pyproject = bar_dir / "pyproject.toml"
    bar_pyproject.write_text(
        """[project]
name = "bar"
version = "0.2.0"
dependencies = [
    "click",
]
""",
        encoding="utf-8",
    )

    return root
