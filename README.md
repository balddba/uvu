# update-uv-packages

A clean standalone Python utility and library to check and update `uv`-managed project dependencies with optional target pinning back to your `pyproject.toml`.

## Features
* **Workspace Support**: Resolves standalone projects or complex `uv` workspaces interactively or via CLI flags.
* **Direct vs Transitive Identification**: Inspects which dependencies are direct in your packages and which are transitive.
* **Pyproject Pinning**: Automatically updates version constraints in `pyproject.toml` files to match the new `uv.lock` values.
* **Safe TOML Handling**: Error-resilient TOML reader with useful CLI messaging.
* **Modern Integration**: Integrates directly with the `uv` toolchain (`uv lock`, `uv sync`).

## Installation

Install via pip or run directly using `uv`:

```bash
pip install update-uv-packages
```

Or run on-the-fly:
```bash
uvx --from update-uv-packages uvu check
```

## CLI Usage

You can use the short command `uvu` or the full command `update-uv-packages`.

### Check available updates
Check for updates across all workspace members:
```bash
uvu check --verbose
```

### Apply updates
Apply updates to specific packages or all packages:
```bash
# Update all available packages
uvu update --all

# Update specific packages
uvu update --packages requests urllib3

# Update and pin modified dependency versions back to pyproject.toml
uvu update --all --pin-updated
```

## Programmatic API Usage

You can import and orchestrate updates directly inside other Python scripts:

```python
from pathlib import Path
from update_uv_packages import UVDependencyManager

# Initialize the manager pointing to your project
manager = UVDependencyManager(start_dir=Path("/path/to/project"))

# Bootstrap layout and workspace members
# (Pass an empty Namespace or CLI args to control options)
import argparse
args = argparse.Namespace(all_members=True, yes=True)
manager.bootstrap(args=args)

# Discover updates
updates = manager.discover_updates()
for update in updates:
    print(f"{update.name}: {update.current} -> {update.latest}")
```
