"""Source-development bootstrap. Never an installer or authoritative host owner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import venv

PREREQUISITE_FAILED = 10
SETUP_FAILED = 11
SUPPORTED = {(3, 13), (3, 14)}


class PrerequisiteError(Exception):
    pass


def check_python(version=None, platform=None):
    version = sys.version_info[:2] if version is None else version
    platform = os.name if platform is None else platform
    if platform != "nt":
        raise PrerequisiteError("These source launchers require Windows; Ubuntu package imports remain supported.")
    if tuple(version) not in SUPPORTED:
        raise PrerequisiteError("Install supported Python 3.13 or 3.14 with the Windows py launcher.")


def check_path(path: Path):
    # Check ancestors before resolve(), so redirection cannot disappear in normalization.
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise PrerequisiteError("Source/environment paths must not contain symlinks or reparse points.")
        if candidate.exists():
            attributes = getattr(candidate.stat(follow_symlinks=False), "st_file_attributes", 0)
            if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise PrerequisiteError("Source/environment paths must not contain reparse points.")


def checkout_root() -> Path:
    root = Path(__file__).absolute().parents[1]
    check_path(root)
    if not (root / "pyproject.toml").is_file() or not (root / "src/soma").is_dir():
        raise PrerequisiteError("Run this adapter from a SOMA source checkout.")
    return root


def environment_python(root: Path) -> Path:
    environment = root / ".venv"
    interpreter = environment / "Scripts/python.exe"
    check_path(interpreter)
    if environment.exists() and not environment.is_dir():
        raise PrerequisiteError(".venv must be a directory; nothing was replaced.")
    return interpreter


def validate_environment(root: Path, *, run=subprocess.run) -> Path:
    interpreter = environment_python(root)
    if not interpreter.is_file():
        raise PrerequisiteError("Repository environment is missing/incomplete. Run soma_setup.bat; nothing was erased.")
    result = run(
        [str(interpreter), "-I", "-c", "import json,sys; print(json.dumps([list(sys.version_info[:2]),sys.prefix,sys.base_prefix]))"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    try:
        version, prefix, base_prefix = json.loads(result.stdout)
        if result.returncode or tuple(version) not in SUPPORTED:
            raise ValueError
        if Path(prefix).resolve() != (root / ".venv").resolve() or prefix == base_prefix:
            raise ValueError
    except (ValueError, TypeError):
        raise PrerequisiteError(".venv is not a supported repository-local Python environment; nothing was erased.") from None
    return interpreter


def setup(root: Path, *, run=subprocess.run, builder=None) -> int:
    print("SOMA source-development setup (not the production installer).", flush=True)
    interpreter = environment_python(root)
    if not interpreter.parent.parent.exists():
        (builder or venv.EnvBuilder(with_pip=True)).create(root / ".venv")
    interpreter = validate_environment(root, run=run)
    result = run(
        [str(interpreter), "-I", "-m", "pip", "--disable-pip-version-check", "--no-input", "install", "-e", ".[test]"],
        cwd=root, check=False,
    )
    if result.returncode:
        print("Source setup failed: check pip output and dependency access, then rerun soma_setup.bat.", file=sys.stderr)
        return SETUP_FAILED
    print("Source environment prepared. Trusted runtime launch remains dependency-pending; see docs/implementation/lld12_source_launchers.md.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "run", "console", "stop"))
    args = parser.parse_args(argv)
    try:
        check_python()
        root = checkout_root()
        if args.action == "setup":
            return setup(root)
        # Runtime actions never install dependencies or discover instances.
        validate_environment(root)
        sys.path.insert(0, str(root / "src"))
        from soma.security.runtime.source_control import source_action
        result = source_action(args.action)
        print(result.message, file=sys.stderr)
        return result.exit_code
    except PrerequisiteError as exc:
        print(f"Source launcher prerequisite failed: {exc}", file=sys.stderr)
        return PREREQUISITE_FAILED
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Source launcher operation failed ({type(exc).__name__}); check the environment and rerun setup.", file=sys.stderr)
        return SETUP_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
