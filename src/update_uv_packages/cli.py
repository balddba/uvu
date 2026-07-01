"""CLI entry point and command parsing for uvu."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version
from tabulate import tabulate
from update_uv_packages.package_update import PackageUpdate
from update_uv_packages.update_report import UpdateReport
from update_uv_packages.uv_dependency_manager import UVDependencyManager


def print_report(*, report: UpdateReport) -> None:
    """Print a post-update report.

    Args:
        report (UpdateReport): Update summary.
    """
    print()
    print("Update report")
    print("=============")
    # Sort and format the package lockfile updates into tabular rows
    if report.lock_updates:
        rows = [
            [update.name, update.current, update.latest]
            for update in sorted(report.lock_updates, key=lambda item: item.name)
        ]
        print(
            tabulate(
                tabular_data=rows,
                headers=["package", "before", "after"],
                tablefmt="simple",
            ),
        )
    else:
        print("No lockfile version changes.")
    # Format and print any pyproject.toml pin modifications
    if report.pyproject_pins:
        print()
        print("pyproject.toml pins")
        rows = [
            [member, group, name, requirement]
            for member, group, name, requirement in report.pyproject_pins
        ]
        print(
            tabulate(
                tabular_data=rows,
                headers=["member", "group", "package", "requirement"],
                tablefmt="simple",
            ),
        )


def add_member_arguments(parser: argparse.ArgumentParser) -> None:
    """Add workspace member selection arguments to a subcommand parser.

    Args:
        parser (argparse.ArgumentParser): Subcommand parser.
    """
    parser.add_argument(
        "--all-members",
        action="store_true",
        help="Include every workspace member (uv workspaces only)",
    )
    parser.add_argument(
        "--members",
        nargs="+",
        metavar="MEMBER",
        help="Workspace members by project name or member path (uv workspaces only)",
    )


def cmd_check(args: argparse.Namespace) -> int:
    """List packages with available upgrades.

    Args:
        args (argparse.Namespace): Parsed CLI arguments.

    Returns:
        int: Process exit code.
    """
    # Initialize dependency manager with the optional custom project directory
    manager = UVDependencyManager(start_dir=args.project_dir)
    # Locate project/workspace files and select active workspace members
    manager.bootstrap(args=args)
    # Retrieve currently locked versions from uv.lock
    lock_versions = manager.load_lock_versions()
    # Query uv lock --dry-run for available updates
    updates = manager.discover_updates()
    # Find outdated packages that are blocked by pyproject.toml constraint patterns
    blocked = manager.discover_blocked_updates(compatible_updates=updates)

    # Print summary of resolved workspace/project structure
    manager.print_layout_summary(lock_versions=lock_versions)
    # Output table of updates that are compatible with pyproject.toml requirements
    manager.print_update_table(
        updates=updates, title=f"Available compatible updates ({len(updates)})"
    )
    # Output table of packages blocked by strict requirements
    if blocked:
        print()
        manager.print_update_table(
            updates=blocked,
            title=f"Outdated packages blocked by constraints ({len(blocked)})",
            show_blocked_by=True,
        )
    # Verbose mode prints all packages that are already at the latest compatible versions
    if args.verbose:
        blocked_names = {item.name for item in blocked}
        up_to_date = sorted(
            name
            for name in lock_versions
            if name not in {item.name for item in updates} and name not in blocked_names
        )
        print()
        print(f"Up to date ({len(up_to_date)})")
        for name in up_to_date:
            print(
                f"  {name}=={lock_versions[name]} ({manager.format_role(package_name=name)})"
            )
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Apply selected package upgrades and optional pyproject pins.

    Args:
        args (argparse.Namespace): Parsed CLI arguments.

    Returns:
        int: Process exit code.
    """
    # Bootstrap the dependency manager to find layout and active members
    manager = UVDependencyManager(start_dir=args.project_dir)
    manager.bootstrap(args=args)
    # Record locked versions before executing updates
    before_lock = manager.load_lock_versions()
    # Discover upgrades and constraints
    available = manager.discover_updates()
    blocked = manager.discover_blocked_updates(compatible_updates=available)

    # Display starting workspace/project summary and available package updates
    manager.print_layout_summary(lock_versions=before_lock)
    manager.print_update_table(
        updates=available, title=f"Available compatible updates ({len(available)})"
    )
    if blocked:
        print()
        manager.print_update_table(
            updates=blocked,
            title=f"Outdated packages blocked by constraints ({len(blocked)})",
            show_blocked_by=True,
        )
    # Exit early if there are no compatible updates and pin-all is not requested
    if not available and not args.pin_all:
        print("Nothing to update.")
        return 0
    # Resolve which packages to update based on CLI flags or interactive input
    if args.packages:
        selected = [manager.normalize_name(name=name) for name in args.packages]
    elif args.all:
        selected = [update.name for update in available]
    elif args.yes:
        selected = [update.name for update in available]
    else:
        selected = manager.prompt_package_selection(updates=available)
    if not selected and not args.pin_all:
        print("No packages selected.")
        return 0

    # Identify selected packages that have blocking constraints in pyproject.toml
    # and update their constraints first.
    blocking_pins: dict[str, str] = {}
    for name in selected:
        if name not in manager.direct_deps:
            continue
        # Find the target version for this package
        target_version = next((u.latest for u in available if u.name == name), None)
        if not target_version:
            continue
        # Check if any of its direct dependency requirements block the target version
        is_blocked = False
        for dep in manager.direct_deps[name]:
            try:
                req = Requirement(dep.requirement)
                if req.specifier and Version(target_version) not in req.specifier:
                    is_blocked = True
                    break
            except Exception:
                # In case of parsing error, treat it as blocked to be safe
                is_blocked = True
                break
        if is_blocked:
            blocking_pins[name] = target_version

    pre_pins = []
    if blocking_pins:
        pre_pins = manager.apply_all_pyproject_pins(
            lock_versions=blocking_pins,
            pin_names=blocking_pins.keys(),
        )
        # Re-load direct dependencies because we modified pyproject.toml
        manager.direct_deps = manager.load_layout_direct_dependencies()

    # Run the uv lock CLI command to write version updates to uv.lock
    if selected:
        result = manager.run_uv_lock(
            dry_run=False,
            upgrade_all=False,
            upgrade_packages=selected,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            print(message, file=sys.stderr)
            return 1
        if result.stdout.strip():
            print(result.stdout.strip())
    # Load lockfile again to check which packages actually upgraded
    after_lock = manager.load_lock_versions()
    lock_updates = [
        PackageUpdate(name=name, current=before_lock[name], latest=after_lock[name])
        for name in sorted(after_lock)
        if name in before_lock and before_lock[name] != after_lock[name]
    ]
    # Determine which direct dependencies to write as exact pins into pyproject.toml files
    pin_targets: set[str] = set()
    if args.pin_all:
        pin_targets.update(manager.direct_deps.keys())
    elif args.pin_updated:
        pin_targets.update(
            update.name for update in lock_updates if update.name in manager.direct_deps
        )
    if pin_targets:
        pins = manager.apply_all_pyproject_pins(
            lock_versions=after_lock,
            pin_names=pin_targets,
        )
    else:
        pins = []

    # Combine pre-pins and post-pins, avoiding duplicates
    all_pins = list(pre_pins)
    pre_pin_keys = {(member, group, name) for member, group, name, _ in pre_pins}
    for pin in pins:
        member, group, name, req = pin
        if (member, group, name) not in pre_pin_keys:
            all_pins.append(pin)

    # Optionally trigger uv sync to align the virtual environment
    if args.sync:
        manager.run_uv_sync()
    # Print the report summarizing changes to lockfile and pyproject files
    print_report(
        report=UpdateReport(lock_updates=lock_updates, pyproject_pins=all_pins)
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """
    parser = argparse.ArgumentParser(
        description="Check and update uv lockfile packages; optionally pin pyproject.toml versions.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Project or workspace member directory (default: repo root)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check", help="List packages with available upgrades"
    )
    check_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also list packages that are already up to date",
    )
    check_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip workspace member prompt and include all members",
    )
    add_member_arguments(parser=check_parser)
    check_parser.set_defaults(func=cmd_check)

    update_parser = subparsers.add_parser(
        "update", help="Upgrade selected packages and report changes"
    )
    update_parser.add_argument(
        "--all",
        action="store_true",
        help="Upgrade every package with an available update",
    )
    update_parser.add_argument(
        "--packages",
        nargs="+",
        metavar="NAME",
        help="Upgrade only these package names (no interactive prompt)",
    )
    update_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive prompts where possible",
    )
    update_parser.add_argument(
        "--pin-all",
        action="store_true",
        help="Pin every direct pyproject dependency to the locked version, even when unchanged",
    )
    update_parser.add_argument(
        "--pin-updated",
        action="store_true",
        help="Pin only direct dependencies that changed in this run",
    )
    update_parser.add_argument(
        "--sync",
        action="store_true",
        help="Run uv sync after updating the lockfile",
    )
    add_member_arguments(parser=update_parser)
    update_parser.set_defaults(func=cmd_update)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str] | None): Optional argument list.

    Returns:
        int: Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args=args))
