"""UpdateReport class summarizing lock and pyproject changes."""

from __future__ import annotations

from dataclasses import dataclass, field

from update_uv_packages.package_update import PackageUpdate


@dataclass
class UpdateReport:
    """Summary of lock and pyproject changes from an update run.

    Attributes:
        lock_updates (list[PackageUpdate]): Packages whose lock versions changed.
        pyproject_pins (list[tuple[str, str, str, str]]): `(member, group, name, requirement)` rows.
    """

    lock_updates: list[PackageUpdate] = field(default_factory=list)
    pyproject_pins: list[tuple[str, str, str, str]] = field(default_factory=list)
