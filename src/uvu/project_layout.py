"""ProjectLayout class representing a resolved uv project or workspace layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from uvu.workspace_member import WorkspaceMember


@dataclass(frozen=True)
class ProjectLayout:
    """Resolved uv project or workspace layout.

    Attributes:
        root (Path): Workspace or project root (directory containing `uv.lock`).
        lock_path (Path): Path to the shared `uv.lock`.
        workspace_members (list[WorkspaceMember]): Workspace members; empty for standalone projects.
        hinted_member (WorkspaceMember | None): Member implied by `--project-dir` when it is not the root.
    """

    root: Path
    lock_path: Path
    workspace_members: list[WorkspaceMember]
    hinted_member: WorkspaceMember | None = None

    @property
    def is_workspace(self) -> bool:
        """Whether the layout represents a uv workspace.

        Returns:
            bool: True if `workspace_members` is non-empty.
        """
        return bool(self.workspace_members)
