"""UVDependencyManager class managing layout, updates, and dependency pinning."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from tabulate import tabulate

from update_uv_packages.direct_dependency import DirectDependency
from update_uv_packages.package_update import PackageUpdate
from update_uv_packages.project_layout import ProjectLayout
from update_uv_packages.workspace_member import WorkspaceMember

UPDATE_LINE_RE = re.compile(r"^Update (\S+) v(.+?) -> v(.+?)$")


class UVDependencyManager:
    """Manages project and workspace layout resolution, updates, and dependency pinning."""

    def __init__(self, start_dir: Path | None = None) -> None:
        """Initialize the dependency manager.

        Args:
            start_dir (Path | None): Starting directory for project layout resolution.
        """
        # Store starting directory from which we'll resolve the project layout
        self.start_dir = start_dir
        # Layout details (root directory, workspace members, lockfile path)
        self.layout: ProjectLayout | None = None
        # Maps package name to its occurrences as direct dependencies in pyproject.toml
        self.direct_deps: dict[str, list[DirectDependency]] = {}
        # Workspace members selected for scanning/updating in the current run
        self.selected_members: list[WorkspaceMember] = []

    def bootstrap(self, args: argparse.Namespace) -> None:
        """Resolve the project layout, select members, and load direct dependencies.

        Args:
            args (argparse.Namespace): Parsed CLI arguments.

        Raises:
            SystemExit: When workspace member selection is cancelled or uv.lock is missing.
        """
        # Find the project/workspace root and record structure layout
        self.layout = self.resolve_project_layout(start=self.start_dir)
        # Ensure uv.lock is present, otherwise we cannot perform dependency resolution
        if not self.layout.lock_path.is_file():
            print(f"Missing uv.lock in {self.layout.root}", file=sys.stderr)
            raise SystemExit(1)
        try:
            # Parse command line flags or interactive input to choose active workspace members
            self.selected_members = self.resolve_selected_members(args=args)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        # Workspace projects require at least one member to be selected for dependency operations
        if self.layout.is_workspace and not self.selected_members:
            print("No workspace members selected.", file=sys.stderr)
            raise SystemExit(1)
        # Extract direct dependencies from the pyproject.toml of selected workspace members
        self.direct_deps = self.load_layout_direct_dependencies()

    def resolve_project_layout(self, start: Path | None = None) -> ProjectLayout:
        """Resolve a standalone project or uv workspace root and optional member hint.

        Args:
            start (Path | None): Starting directory; defaults to the script parent.

        Returns:
            ProjectLayout: Resolved layout with lockfile location and workspace members.

        Raises:
            FileNotFoundError: When no `pyproject.toml` and `uv.lock` pair can be found.
        """
        current = (start or Path.cwd()).resolve()

        # If the starting directory contains a pyproject.toml but not a uv.lock,
        # it is likely a workspace member directory rather than the workspace root.
        hinted_path: Path | None = None
        if (current / "pyproject.toml").is_file() and not (
            current / "uv.lock"
        ).is_file():
            hinted_path = current

        # Walk up directory tree to find the root directory containing both pyproject.toml and uv.lock
        search = current
        while True:
            pyproject_path = search / "pyproject.toml"
            lock_path = search / "uv.lock"
            if pyproject_path.is_file() and lock_path.is_file():
                # Discover workspace members from the resolved workspace root
                members = self.discover_workspace_members(workspace_root=search)
                hinted_member = None
                if hinted_path is not None:
                    for member in members:
                        if member.path == hinted_path:
                            hinted_member = member
                            break
                return ProjectLayout(
                    root=search,
                    lock_path=lock_path,
                    workspace_members=members,
                    hinted_member=hinted_member,
                )
            parent = search.parent
            if parent == search:
                break
            search = parent
        raise FileNotFoundError(
            f"Could not find pyproject.toml and uv.lock from {current}"
        )

    def discover_workspace_members(
        self, *, workspace_root: Path
    ) -> list[WorkspaceMember]:
        """Load workspace members from `[tool.uv.workspace]`.

        Args:
            workspace_root (Path): Workspace root directory.

        Returns:
            list[WorkspaceMember]: Deduplicated workspace members including the root package.
        """
        pyproject_path = workspace_root / "pyproject.toml"
        data = self._load_toml(path=pyproject_path)
        # Parse the workspace configuration block under [tool.uv.workspace]
        workspace = data.get("tool", {}).get("uv", {}).get("workspace")
        if workspace is None:
            return []
        members: list[WorkspaceMember] = []
        seen_paths: set[Path] = set()

        # Helper to load and append workspace member metadata
        def add_member(*, path: Path, relative_path: str) -> None:
            resolved = path.resolve()
            member_pyproject = resolved / "pyproject.toml"
            if resolved in seen_paths or not member_pyproject.is_file():
                return
            seen_paths.add(resolved)
            member_data = self._load_toml(path=member_pyproject)
            project_name = str(
                member_data.get("project", {}).get("name", relative_path)
            )
            members.append(
                WorkspaceMember(
                    name=project_name,
                    path=resolved,
                    relative_path=relative_path,
                ),
            )

        # Include the workspace root itself as a member
        add_member(path=workspace_root, relative_path=".")
        # Include all explicit member paths listed in the workspace configuration
        for relative in workspace.get("members", []):
            add_member(path=workspace_root / str(relative), relative_path=str(relative))
        return members

    def load_lock_versions(self) -> dict[str, str]:
        """Load package versions from `uv.lock`.

        Returns:
            dict[str, str]: Normalized package name to locked version.
        """
        assert self.layout is not None
        # Load and parse the contents of the lockfile using tomllib
        data = self._load_toml(path=self.layout.lock_path)
        versions: dict[str, str] = {}
        # Traverse packages listed in the lockfile to compile a map of names to versions
        for package in data.get("package", []):
            name = self.normalize_name(name=str(package["name"]))
            versions[name] = str(package["version"])
        return versions

    def load_direct_dependencies(
        self, *, pyproject_path: Path, member_label: str
    ) -> list[DirectDependency]:
        """Load direct dependencies from one `pyproject.toml`.

        Args:
            pyproject_path (Path): Path to `pyproject.toml`.
            member_label (str): Owning workspace member or project name.

        Returns:
            list[DirectDependency]: Direct dependency rows for the file.
        """
        data = self._load_toml(path=pyproject_path)
        direct: list[DirectDependency] = []
        # Load standard project dependencies listed in [project.dependencies]
        project_deps = data.get("project", {}).get("dependencies", [])
        for requirement in project_deps:
            req = Requirement(str(requirement))
            # Ignore URL/VCS dependencies since they do not target package registry versions
            if req.url:
                continue
            direct.append(
                DirectDependency(
                    name=self.normalize_name(name=req.name),
                    requirement=str(requirement),
                    group="project",
                    member_label=member_label,
                    pyproject_path=pyproject_path,
                ),
            )
        # Load group-specific dependencies listed in [dependency-groups]
        for group_name, requirements in data.get("dependency-groups", {}).items():
            for requirement in requirements:
                req = Requirement(str(requirement))
                if req.url:
                    continue
                direct.append(
                    DirectDependency(
                        name=self.normalize_name(name=req.name),
                        requirement=str(requirement),
                        group=str(group_name),
                        member_label=member_label,
                        pyproject_path=pyproject_path,
                    ),
                )
        return direct

    def build_direct_index(
        self, deps: Iterable[DirectDependency]
    ) -> dict[str, list[DirectDependency]]:
        """Index direct dependencies by normalized package name.

        Args:
            deps (Iterable[DirectDependency]): Direct dependency rows.

        Returns:
            dict[str, list[DirectDependency]]: Package name to one or more direct dependency rows.
        """
        # Group direct dependency declarations by their PEP 503 normalized name
        index: dict[str, list[DirectDependency]] = defaultdict(list)
        for dep in deps:
            index[dep.name].append(dep)
        return dict(index)

    def load_layout_direct_dependencies(self) -> dict[str, list[DirectDependency]]:
        """Load direct dependencies for the selected workspace members or standalone project.

        Returns:
            dict[str, list[DirectDependency]]: Direct dependency index.
        """
        assert self.layout is not None
        # For workspace projects, iterate and extract from each selected member's pyproject.toml
        if self.layout.is_workspace:
            deps: list[DirectDependency] = []
            for member in self.selected_members:
                deps.extend(
                    self.load_direct_dependencies(
                        pyproject_path=member.path / "pyproject.toml",
                        member_label=member.name,
                    ),
                )
            return self.build_direct_index(deps=deps)
        # For standalone projects, extract from the main pyproject.toml at layout root
        project_name = (
            self._load_toml(path=self.layout.root / "pyproject.toml")
            .get("project", {})
            .get("name", self.layout.root.name)
        )
        deps = self.load_direct_dependencies(
            pyproject_path=self.layout.root / "pyproject.toml",
            member_label=str(project_name),
        )
        return self.build_direct_index(deps=deps)

    def member_matches_token(self, *, member: WorkspaceMember, token: str) -> bool:
        """Return True when a token matches a workspace member.

        Args:
            member (WorkspaceMember): Workspace member row.
            token (str): User token (name, path, or index).

        Returns:
            bool: True when the token identifies the member.
        """
        normalized = token.strip().lower()
        # Verify match against member's package name, relative path, or absolute path
        return normalized in {
            member.name.lower(),
            member.relative_path.lower(),
            str(member.path).lower(),
        }

    def prompt_workspace_member_selection(
        self, *, members: list[WorkspaceMember], hinted_member: WorkspaceMember | None
    ) -> list[WorkspaceMember]:
        """Interactively choose workspace members to include.

        Args:
            members (list[WorkspaceMember]): Workspace members.
            hinted_member (WorkspaceMember | None): Member implied by `--project-dir`.

        Returns:
            list[WorkspaceMember]: Selected workspace members.
        """
        if not members:
            return []
        print("Workspace members")
        # Format workspace members list with numbering, name, and relative path
        rows = [
            [index, member.name, member.relative_path]
            for index, member in enumerate(members, start=1)
        ]
        print(
            tabulate(
                tabular_data=rows,
                headers=["#", "member", "path"],
                tablefmt="simple",
            ),
        )
        # Highlight hinted member (implied by the directory where script was run)
        if hinted_member is not None:
            print(
                f"Hint: started from member {hinted_member.name} ({hinted_member.relative_path})"
            )
        print()
        print(
            "Enter member numbers to include (comma-separated), `all`, or `q` to cancel."
        )
        choice = input("Member selection: ").strip().lower()
        # Handle cancel request
        if choice in {"", "q", "quit"}:
            return []
        # Return all members if requested
        if choice == "all":
            return list(members)
        selected: list[WorkspaceMember] = []
        # Parse comma-separated inputs (which can be numbers or name tokens)
        for part in choice.split(","):
            token = part.strip()
            if not token:
                continue
            if token.isdigit():
                index = int(token)
                if 1 <= index <= len(members):
                    selected.append(members[index - 1])
                continue
            for member in members:
                if self.member_matches_token(member=member, token=token):
                    selected.append(member)
        # Remove duplicates while maintaining order
        unique: list[WorkspaceMember] = []
        seen: set[Path] = set()
        for member in selected:
            if member.path in seen:
                continue
            seen.add(member.path)
            unique.append(member)
        return unique

    def resolve_selected_members(
        self, *, args: argparse.Namespace
    ) -> list[WorkspaceMember]:
        """Resolve workspace members from CLI flags or interactive selection.

        Args:
            args (argparse.Namespace): Parsed CLI arguments.

        Returns:
            list[WorkspaceMember]: Selected workspace members; empty for standalone projects.
        """
        assert self.layout is not None
        if not self.layout.is_workspace:
            return []
        # Return all members if --all-members flag is specified
        if args.all_members:
            return list(self.layout.workspace_members)
        # Parse and match explicit member names/paths if --members flag is provided
        if args.members:
            selected: list[WorkspaceMember] = []
            for token in args.members:
                matches = [
                    member
                    for member in self.layout.workspace_members
                    if self.member_matches_token(member=member, token=token)
                ]
                if not matches:
                    raise ValueError(f"Unknown workspace member: {token}")
                selected.extend(matches)
            # Deduplicate the selected members list by their absolute path
            unique: list[WorkspaceMember] = []
            seen: set[Path] = set()
            for member in selected:
                if member.path in seen:
                    continue
                seen.add(member.path)
                unique.append(member)
            return unique
        # If --yes is set, default to the hinted subdirectory member or all members
        if args.yes:
            if self.layout.hinted_member is not None:
                return [self.layout.hinted_member]
            return list(self.layout.workspace_members)
        # Interactively prompt the user for member selection
        selected = self.prompt_workspace_member_selection(
            members=self.layout.workspace_members,
            hinted_member=self.layout.hinted_member,
        )
        if not selected:
            return []
        return selected

    def run_uv_lock(
        self, *, dry_run: bool, upgrade_all: bool, upgrade_packages: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        """Run `uv lock` with optional upgrade flags.

        Args:
            dry_run (bool): Pass `--dry-run` when True.
            upgrade_all (bool): Pass `--upgrade` when True.
            upgrade_packages (Sequence[str]): Package names for `--upgrade-package`.

        Returns:
            subprocess.CompletedProcess[str]: Completed uv process.
        """
        assert self.layout is not None
        # Construct the basic uv lock command
        command = ["uv", "lock"]
        # Dry-run allows querying proposed changes without saving them to uv.lock
        if dry_run:
            command.append("--dry-run")
        # Upgrade all packages to their latest compatible versions
        if upgrade_all:
            command.append("--upgrade")
        # Selectively upgrade specific package names
        for package_name in upgrade_packages:
            command.extend(["--upgrade-package", package_name])
        try:
            return subprocess.run(
                command,
                cwd=self.layout.root,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            # Handle absence of uv binary in PATH cleanly
            print(
                "Error: 'uv' executable not found in PATH. Please install uv (https://github.com/astral-sh/uv) to run this script.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc

    def parse_upgrade_lines(self, output: str) -> list[PackageUpdate]:
        """Parse `Update name vX -> vY` lines from uv stdout/stderr.

        Args:
            output (str): Combined uv output.

        Returns:
            list[PackageUpdate]: Parsed upgrade rows.
        """
        updates: list[PackageUpdate] = []
        # Parse stdout/stderr lines matching the standard update log output from uv
        for line in output.splitlines():
            match = UPDATE_LINE_RE.match(string=line.strip())
            if match is None:
                continue
            updates.append(
                PackageUpdate(
                    name=self.normalize_name(name=match.group(1)),
                    current=match.group(2),
                    latest=match.group(3),
                ),
            )
        return updates

    def discover_updates(
        self, *, upgrade_packages: Sequence[str] | None = None
    ) -> list[PackageUpdate]:
        """Discover available upgrades via `uv lock --dry-run` and outdated direct dependencies.

        Args:
            upgrade_packages (Sequence[str] | None): Specific packages to probe; all when None.

        Returns:
            list[PackageUpdate]: Available upgrades.

        Raises:
            RuntimeError: When `uv lock --dry-run` fails.
        """
        # Run uv lock --dry-run for specified packages, or for all packages if None
        if upgrade_packages:
            result = self.run_uv_lock(
                dry_run=True,
                upgrade_all=False,
                upgrade_packages=[
                    self.normalize_name(name=name) for name in upgrade_packages
                ],
            )
        else:
            result = self.run_uv_lock(
                dry_run=True,
                upgrade_all=True,
                upgrade_packages=[],
            )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"uv lock --dry-run failed: {message}")
        # Parse stdout and stderr log outputs to retrieve proposed update details
        compatible_updates = self.parse_upgrade_lines(
            output=f"{result.stdout}\n{result.stderr}"
        )
        compatible_names = {u.name for u in compatible_updates}

        # Query all outdated packages using uv tree --outdated
        tree_result = self.run_uv_tree_outdated()
        if tree_result.returncode == 0:
            all_outdated = self.parse_tree_outdated_lines(output=tree_result.stdout)
            # If target packages are specified, filter candidates
            if upgrade_packages:
                targets = {self.normalize_name(name=name) for name in upgrade_packages}
            else:
                targets = set(self.direct_deps.keys())

            for u in all_outdated:
                if u.name in targets and u.name not in compatible_names:
                    if u.name in self.direct_deps:
                        compatible_updates.append(u)
                        compatible_names.add(u.name)

        return compatible_updates

    def format_role(self, *, package_name: str) -> str:
        """Describe whether a package is direct or transitive.

        Args:
            package_name (str): Normalized package name.

        Returns:
            str: Role label for display.
        """
        deps = self.direct_deps.get(package_name)
        # Packages not in the direct dependencies list are transitive/indirect dependencies
        if not deps:
            return "transitive"
        # Compile unique labels indicating which workspace members and groups require this package
        labels = sorted({f"{dep.member_label}/{dep.group}" for dep in deps})
        return f"direct ({', '.join(labels)})"

    def load_reverse_dependency_map(self) -> dict[str, list[str]]:
        """Load reverse dependency map from the lockfile.

        Returns:
            dict[str, list[str]]: Mapping of dependency names to parent package names.
        """
        if not self.layout or not self.layout.lock_path.is_file():
            return {}
        try:
            data = self._load_toml(path=self.layout.lock_path)
        except Exception:
            return {}
        reverse_map: dict[str, list[str]] = defaultdict(list)
        # Parse lockfile package relationships to build a child-to-parent reverse dependency index
        for package in data.get("package", []):
            parent_name = self.normalize_name(name=str(package["name"]))
            for dep in package.get("dependencies", []):
                if isinstance(dep, dict):
                    dep_name = self.normalize_name(name=str(dep["name"]))
                else:
                    try:
                        dep_name = self.normalize_name(name=Requirement(str(dep)).name)
                    except Exception:
                        dep_name = self.normalize_name(name=str(dep).split()[0])
                reverse_map[dep_name].append(parent_name)
        return dict(reverse_map)

    def get_blocker_description(
        self, *, package_name: str, reverse_map: dict[str, list[str]]
    ) -> str:
        """Determine what is blocking a package update.

        Args:
            package_name (str): Normalized package name.
            reverse_map (dict[str, list[str]]): Map of package name to parent package names.

        Returns:
            str: Blocker description label.
        """
        # Check if direct dependencies are imposing constraint requirements
        direct_deps = self.direct_deps.get(package_name)
        if direct_deps:
            constraints = ", ".join(dep.requirement for dep in direct_deps)
            return f"pyproject.toml ({constraints})"

        # Check if parent packages are requiring/pinning this package version
        parents = reverse_map.get(package_name, [])
        if parents:
            return f"required by {', '.join(sorted(parents))}"

        return "unknown constraint"

    def print_update_table(
        self, *, updates: list[PackageUpdate], title: str, show_blocked_by: bool = False
    ) -> None:
        """Print a tabular list of available upgrades.

        Args:
            updates (list[PackageUpdate]): Upgrade rows.
            title (str): Table heading.
            show_blocked_by (bool): Include blocked by column when True.
        """
        if not updates:
            print(f"{title}: none")
            return
        # Load the child-to-parent mapping only if showing blocker explanations
        reverse_map = self.load_reverse_dependency_map() if show_blocked_by else {}
        headers = ["#", "package", "locked", "latest", "role"]
        if show_blocked_by:
            headers.append("blocked by")
        rows = []
        for index, update in enumerate(updates, start=1):
            row = [
                index,
                update.name,
                update.current,
                update.latest,
                self.format_role(package_name=update.name),
            ]
            if show_blocked_by:
                row.append(
                    self.get_blocker_description(
                        package_name=update.name, reverse_map=reverse_map
                    ),
                )
            rows.append(row)
        print(title)
        print(
            tabulate(
                tabular_data=rows,
                headers=headers,
                tablefmt="simple",
            ),
        )

    def prompt_package_selection(self, *, updates: list[PackageUpdate]) -> list[str]:
        """Interactively choose packages to upgrade.

        Args:
            updates (list[PackageUpdate]): Available upgrades.

        Returns:
            list[str]: Selected normalized package names.
        """
        if not updates:
            return []
        print()
        print(
            "Enter package numbers to update (comma-separated), `all`, or `q` to cancel."
        )
        choice = input("Package selection: ").strip().lower()
        if choice in {"", "q", "quit"}:
            return []
        # Return all packages if requested
        if choice == "all":
            return [update.name for update in updates]
        selected: list[str] = []
        # Parse comma-separated numbers or explicit package name queries
        for part in choice.split(","):
            token = part.strip()
            if not token:
                continue
            if token.isdigit():
                index = int(token)
                if 1 <= index <= len(updates):
                    selected.append(updates[index - 1].name)
                continue
            selected.append(self.normalize_name(name=token))
        return sorted(set(selected))

    def pinned_requirement(self, *, dep: DirectDependency, version: str) -> str:
        """Build an exact-pin PEP 508 requirement for a direct dependency.

        Args:
            dep (DirectDependency): Existing direct dependency metadata.
            version (str): Version from `uv.lock`.

        Returns:
            str: `name==version` requirement, preserving extras when present.
        """
        # Parse requirement using packaging to preserve extras/markers
        req = Requirement(dep.requirement)
        extras = "".join(sorted(f"[{extra}]" for extra in req.extras))
        marker = f" ; {req.marker}" if req.marker else ""
        return f"{req.name}{extras}=={version}{marker}"

    def apply_pyproject_pins(
        self,
        *,
        pyproject_path: Path,
        lock_versions: dict[str, str],
        deps: Sequence[DirectDependency],
        pin_names: Iterable[str],
        member_label: str,
    ) -> list[tuple[str, str, str, str]]:
        """Rewrite selected direct dependencies in one `pyproject.toml` to exact pins.

        Args:
            pyproject_path (Path): Path to `pyproject.toml`.
            lock_versions (dict[str, str]): Versions from `uv.lock`.
            deps (Sequence[DirectDependency]): Direct dependencies owned by the file.
            pin_names (Iterable[str]): Normalized package names to pin.
            member_label (str): Workspace member label for reporting.

        Returns:
            list[tuple[str, str, str, str]]: Applied pin rows `(member, group, name, requirement)`.
        """
        text = pyproject_path.read_text(encoding="utf-8")
        applied: list[tuple[str, str, str, str]] = []
        targets = {self.normalize_name(name=name) for name in pin_names}
        for dep in deps:
            if dep.name not in targets:
                continue
            version = lock_versions.get(dep.name)
            if version is None:
                continue
            new_requirement = self.pinned_requirement(dep=dep, version=version)
            if new_requirement == dep.requirement:
                continue
            # Perform direct text replacement in pyproject.toml instead of parsing TOML.
            # This preserves comments, structure, and original file formatting.
            # We check both single and double quotes to match standard TOML arrays/strings.
            for quote in ('"', "'"):
                old = f"{quote}{dep.requirement}{quote}"
                new = f"{quote}{new_requirement}{quote}"
                if old in text:
                    text = text.replace(old, new, 1)
                    applied.append((member_label, dep.group, dep.name, new_requirement))
                    break
        if applied:
            pyproject_path.write_text(data=text, encoding="utf-8")
        return applied

    def apply_all_pyproject_pins(
        self, *, lock_versions: dict[str, str], pin_names: Iterable[str]
    ) -> list[tuple[str, str, str, str]]:
        """Pin selected direct dependencies across one or more `pyproject.toml` files.

        Args:
            lock_versions (dict[str, str]): Versions from `uv.lock`.
            pin_names (Iterable[str]): Normalized package names to pin.

        Returns:
            list[tuple[str, str, str, str]]: Applied pin rows.
        """
        # Group target direct dependencies by their parent pyproject.toml path
        by_path: dict[Path, list[DirectDependency]] = defaultdict(list)
        for deps in self.direct_deps.values():
            for dep in deps:
                by_path[dep.pyproject_path].append(dep)
        applied: list[tuple[str, str, str, str]] = []
        targets = {self.normalize_name(name=name) for name in pin_names}
        # Rewrite each file and collect all applied modifications
        for pyproject_path, deps in by_path.items():
            member_label = deps[0].member_label
            applied.extend(
                self.apply_pyproject_pins(
                    pyproject_path=pyproject_path,
                    lock_versions=lock_versions,
                    deps=deps,
                    pin_names=targets,
                    member_label=member_label,
                ),
            )
        return applied

    def run_uv_sync(self) -> None:
        """Sync the virtual environment after a lock update.

        Raises:
            SystemExit: When uv sync is not found or fails.
        """
        assert self.layout is not None
        try:
            # Execute uv sync to install the updated lockfile packages into .venv
            result = subprocess.run(
                ["uv", "sync"],
                cwd=self.layout.root,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            # Handle missing uv binary gracefully
            print(
                "Error: 'uv' executable not found in PATH. Please install uv (https://github.com/astral-sh/uv) to run this script.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"uv sync failed: {message}")

    def print_layout_summary(self, *, lock_versions: dict[str, str]) -> None:
        """Print project or workspace summary lines.

        Args:
            lock_versions (dict[str, str]): Locked package versions.
        """
        assert self.layout is not None
        direct_names = set(self.direct_deps)
        transitive_count = len(
            [name for name in lock_versions if name not in direct_names]
        )
        # Summarize workspace root and active members, or standalone project root
        if self.layout.is_workspace:
            member_names = ", ".join(member.name for member in self.selected_members)
            print(f"Workspace: {self.layout.root}")
            print(f"Members: {member_names}")
        else:
            print(f"Project: {self.layout.root}")
        print(
            f"Locked packages: {len(lock_versions)} ({len(direct_names)} direct in scope, {transitive_count} transitive)",
        )

    def run_uv_tree_outdated(self) -> subprocess.CompletedProcess[str]:
        """Run `uv tree --outdated` to find all outdated packages.

        Returns:
            subprocess.CompletedProcess[str]: Completed process containing the tree output.
        """
        assert self.layout is not None
        try:
            # Execute uv tree --outdated to view dependencies with newer available versions
            return subprocess.run(
                ["uv", "tree", "--outdated"],
                cwd=self.layout.root,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            # Handle missing uv executable in PATH
            print(
                "Error: 'uv' executable not found in PATH. Please install uv (https://github.com/astral-sh/uv) to run this script.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc

    def parse_tree_outdated_lines(self, output: str) -> list[PackageUpdate]:
        """Parse outdated packages from `uv tree --outdated` output.

        Args:
            output (str): Standard output from uv tree --outdated.

        Returns:
            list[PackageUpdate]: List of all outdated packages.
        """
        # Regex captures package name, locked version, and latest version from tree lines
        pattern = re.compile(r"(\S+)\s+v(\S+)\s+\(latest:\s+v?(\S+)\)")
        updates: list[PackageUpdate] = []
        for line in output.splitlines():
            match = pattern.search(string=line)
            if not match:
                continue
            name = self.normalize_name(name=match.group(1))
            current = match.group(2)
            latest = match.group(3)
            updates.append(PackageUpdate(name=name, current=current, latest=latest))
        return updates

    def discover_blocked_updates(
        self, *, compatible_updates: list[PackageUpdate]
    ) -> list[PackageUpdate]:
        """Find outdated packages that are blocked by pyproject.toml constraints.

        Args:
            compatible_updates (list[PackageUpdate]): Upgrades that can be safely applied.

        Returns:
            list[PackageUpdate]: Outdated packages blocked by constraints.
        """
        # Run uv tree --outdated to get all packages that have newer upstream versions
        result = self.run_uv_tree_outdated()
        if result.returncode != 0:
            return []
        all_outdated = self.parse_tree_outdated_lines(output=result.stdout)
        # Any package in all_outdated that is NOT in compatible_updates
        # is considered blocked by some local version range constraint.
        compatible_names = {u.name for u in compatible_updates}
        return [u for u in all_outdated if u.name not in compatible_names]

    def normalize_name(self, name: str) -> str:
        """Normalize a distribution name for comparisons.

        Args:
            name (str): Raw distribution or requirement name.

        Returns:
            str: PEP 503-normalized name.
        """
        return canonicalize_name(name)

    def _load_toml(self, *, path: Path) -> dict[str, Any]:
        """Load and parse a TOML file, handling errors gracefully.

        Args:
            path (Path): Path to the TOML file.

        Returns:
            dict[str, Any]: Parsed TOML content.

        Raises:
            SystemExit: When the file cannot be read or is invalid TOML.
        """
        try:
            # Load path file and parse into dictionary using standard tomllib
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            print(f"Error: File not found: {path}", file=sys.stderr)
            raise SystemExit(1) from exc
        except PermissionError as exc:
            print(f"Error: Permission denied reading: {path}", file=sys.stderr)
            raise SystemExit(1) from exc
        except tomllib.TOMLDecodeError as exc:
            print(f"Error: Invalid TOML format in {path}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
