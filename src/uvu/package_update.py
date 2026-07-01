"""PackageUpdate class representing a package bump reported by uv lock."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PackageUpdate:
    """A single package version bump reported by `uv lock`.

    Attributes:
        name (str): Distribution name.
        current (str): Locked version before upgrade.
        latest (str): Resolved version after upgrade.
    """

    name: str
    current: str
    latest: str
