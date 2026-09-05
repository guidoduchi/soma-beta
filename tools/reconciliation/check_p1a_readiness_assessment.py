#!/usr/bin/env python3
"""Check catalogue/assessment identity accounting; never certify semantics."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

WAVES = ["P1A_W1_FOUNDATION_SETTINGS.md", "P1A_W2_TICKETS_SOURCE.md",
         "P1A_W3_OBJECTIVES_WORK.md", "P1A_W4_INVENTORY.md",
         "P1A_W5_INFRASTRUCTURE.md", "P1A_W6_COMMUNICATIONS.md",
         "P1A_W7_OVERVIEW_CROSSDOMAIN.md"]
ASSESSMENT = "docs/use-cases/P1A_READINESS_ASSESSMENT_2026_09_05.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(repo: Path):
    catalogue = {}
    wave_counts = Counter()
    thin = []
    for number, filename in enumerate(WAVES, 1):
        text = (repo / "docs/use-cases" / filename).read_text(encoding="utf-8")
        blocks = re.split(r"(?m)^## (UC-\d{3}) — ([^\n]+)\n", text)
        for index in range(1, len(blocks), 3):
            identity, title, body = blocks[index:index + 3]
            require(identity not in catalogue, f"duplicate catalogue ID: {identity}")
            status_match = re.search(r"(?m)^Status: \*\*([^\n]+)", body)
            require(status_match is not None, f"missing status: {identity}")
            status = status_match.group(1)
            if status.startswith("Accepted"):
                state = "A"
            elif status.startswith("Proposed"):
                state = "P"
            elif status.startswith("Goal Seed"):
                state = "S"
            elif status.startswith("Merged/retired"):
                state = "R"
            else:
                raise ValueError(f"unrecognized catalogue state: {identity}: {status}")
            wave = f"W{number}"
            catalogue[identity] = (wave, state)
            wave_counts[wave] += 1
            if state == "S" and not re.search(r"\*\*Main (?:flow|success flow):\*\*", body):
                thin.append(identity)
    expected = {f"UC-{n:03d}" for n in range(1, 96)}
    require(set(catalogue) == expected, "catalogue is not exactly UC-001..095")
    counts = Counter(state for _, state in catalogue.values())
    require(counts == {"A": 1, "P": 1, "S": 92, "R": 1}, f"unexpected statuses: {counts}")
    require(catalogue["UC-001"][1] == "A" and catalogue["UC-002"][1] == "P"
            and catalogue["UC-043"][1] == "R", "accepted/proposed/retired identity changed")
    assessment = (repo / ASSESSMENT).read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| (UC-\d{3}) \| (W[1-7]) \| ([APSR]) \| (.+) \|$", assessment)
    require(len(rows) == 95, "assessment must contain exactly 95 individual rows")
    ids = [row[0] for row in rows]
    require(ids == sorted(expected), "assessment IDs must be unique, complete and numerically ordered")
    for identity, wave, state, focus in rows:
        require(catalogue[identity] == (wave, state), f"assessment/source mismatch: {identity}")
        require(len(focus.strip()) >= 30, f"missing specific review focus: {identity}")
    return {"result": "PASS", "scope": "identity/status accounting only; no semantic certification",
            "catalogue_identities": len(catalogue), "assessment_rows": len(rows),
            "active": counts["A"] + counts["P"] + counts["S"], "states": dict(counts),
            "identities_by_wave_including_retired": dict(wave_counts),
            "seeds_without_main_flow": sorted(thin), "owner_review": "PAUSED_UNTIL_A2_PASS"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    print(json.dumps(check(Path(args.repo).resolve()), indent=2))


if __name__ == "__main__":
    main()
