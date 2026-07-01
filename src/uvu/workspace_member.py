"""WorkspaceMember class representing a single package in a uv workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceMember:
    """One package in a uv workspace.

    Attributes:
        name (str): `project.name` from the member `pyproject.toml`.
        path (Path): Absolute path to the member directory.
        relative_path (str): Member path relative to the workspace root.
    """

    name: str
    path: Path
    relative_path: str
