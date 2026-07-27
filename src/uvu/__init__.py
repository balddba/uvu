"""Check and update uv-managed project dependencies with optional pyproject pinning."""

from __future__ import annotations

from uvu.direct_dependency import DirectDependency
from uvu.package_update import PackageUpdate
from uvu.project_layout import ProjectLayout
from uvu.update_report import UpdateReport
from uvu.uv_dependency_manager import UVDependencyManager
from uvu.workspace_member import WorkspaceMember

__version__ = "0.2.3"

__all__ = [
    "DirectDependency",
    "PackageUpdate",
    "ProjectLayout",
    "UpdateReport",
    "UVDependencyManager",
    "WorkspaceMember",
]
