"""DirectDependency class representing a single direct dependency in pyproject.toml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DirectDependency:
    """One direct dependency declared in `pyproject.toml`.

    Attributes:
        name (str): Normalized distribution name.
        requirement (str): Original PEP 508 requirement string.
        group (str): `project` or a dependency-group name.
        member_label (str): Workspace member or project name owning this dependency.
        pyproject_path (Path): `pyproject.toml` file containing the requirement.
    """

    name: str
    requirement: str
    group: str
    member_label: str
    pyproject_path: Path
