"""Fail closed on staging or publishing the private root tmp directory.

Only Git paths/commit metadata are inspected. Never read or print sample content
or filenames. The local hooks and CI use the same check.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def check(*, pre_push=False):
    if git("ls-files", "-z", "--", ":(top)tmp"):
        raise ValueError("Private local samples are staged or tracked; publication is blocked.")
    refs = ["HEAD"]
    if pre_push:
        refs = []
        for line in sys.stdin:
            parts = line.split()
            if len(parts) != 4 or re.fullmatch(r"[0-9a-f]{40}", parts[1]) is None:
                raise ValueError("Local-only push metadata could not be verified.")
            if parts[1] != "0" * 40:
                refs.append(parts[1])
    if refs and git("rev-parse", "--is-shallow-repository").strip() == b"true":
        raise ValueError("Full local history is required to verify private sample exclusion.")
    for ref in refs:
        # Check history too: deleting a private file later does not remove it
        # from commits being pushed. Output is commit metadata only.
        if git("log", "-1", "--format=%H", ref, "--", ":(top)tmp").strip():
            raise ValueError("Private local samples occur in publication history; publication is blocked.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre-push", action="store_true")
    args = parser.parse_args()
    try:
        check(pre_push=args.pre_push)
    except (ValueError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "Local-only publication check could not be verified."
        print(message, file=sys.stderr)
        return 1
    print("Verified: private local samples are excluded from Git publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
