#!/usr/bin/env python3
"""Pass-2 fail-closed validation for concrete durable-job contracts.

LLD-01 owns durable-job coordination. Workflow-owning packets that use durable
jobs must publish a versioned jobs/*.json registry whose entries satisfy the
Foundation job_type_contract. This checker validates actual packet
manifests/registries rather than treating prose or traceability as a substitute
for a runnable job contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LLD_ROOT = ROOT / "spec/lld"


def load(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def manifest_paths(packet_root: Path) -> list[str]:
    doc = load(packet_root / "_index.json")
    out: list[str] = []
    for key in ("packet_files", "normative_paths"):
        value = doc.get(key, [])
        if isinstance(value, list):
            out.extend(str(x) for x in value if isinstance(x, str))
    return sorted(set(out))


def packet_owns_durable_jobs(packet_root: Path, manifest: list[str]) -> bool:
    """Detect owned worker persistence, not merely a dependency mention."""
    strong_needles = (
        "internal durable-job",
        "internal durable job",
        "durable job ref",
        "durable-job writer",
        "durable-job transition",
        "enqueue a durable",
        "enqueue durable",
        "job_id text",
        "job_id\"",
    )
    for rel in manifest:
        if rel.startswith("tests/") or rel.startswith("jobs/"):
            continue
        path = packet_root / rel
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        text = path.read_text(encoding="utf-8").lower()
        if any(n in text for n in strong_needles):
            return True
    return False


def main() -> int:
    findings: list[str] = []
    global_index = load(LLD_ROOT / "_index.json")

    foundation = LLD_ROOT / "foundation-runtime"
    coordinator = load(foundation / "algorithms/job-coordinator.json")
    required = coordinator.get("job_type_contract", {}).get("required_fields", [])
    required_fields = [str(x) for x in required if isinstance(x, str)]
    if not required_fields:
        findings.append("LLD-01 job coordinator exposes no machine-readable required_fields")
        required_fields = [
            "job_type", "contract_version", "payload_schema", "checkpoint_schema",
            "retry_policy", "crash_recovery_policy", "cancellation_policy",
            "sensitive_field_policy",
        ]

    for packet in global_index.get("packets", []):
        if not isinstance(packet, dict):
            continue
        packet_id = str(packet.get("id", ""))
        packet_root = ROOT / str(packet.get("path", ""))
        if not packet_id or not (packet_root / "_index.json").is_file():
            continue
        manifest = manifest_paths(packet_root)
        job_paths = [rel for rel in manifest if rel.startswith("jobs/") and rel.endswith(".json")]
        owns_jobs = packet_owns_durable_jobs(packet_root, manifest)

        if packet_id != "LLD-01" and owns_jobs and not job_paths:
            findings.append(f"{packet_id} owns durable-job workflow state but has no manifest-listed jobs/*.json registry")
            continue

        seen_job_types: set[tuple[str, int]] = set()
        for rel in job_paths:
            path = packet_root / rel
            if not path.is_file():
                findings.append(f"{packet_id} manifest job registry missing on disk: {rel}")
                continue
            doc = load(path)
            jobs = doc.get("jobs", []) if isinstance(doc, dict) else []
            if not isinstance(jobs, list):
                findings.append(f"{packet_id}:{rel} jobs must be a list")
                continue
            for idx, job in enumerate(jobs):
                if not isinstance(job, dict):
                    findings.append(f"{packet_id}:{rel} job[{idx}] is not an object")
                    continue
                job_name = str(job.get("job_type", f"job[{idx}]"))
                version = job.get("contract_version")
                missing = [field for field in required_fields if field not in job]
                if missing:
                    findings.append(
                        f"{packet_id}:{rel}:{job_name} missing Foundation-required fields: {','.join(missing)}"
                    )
                if not isinstance(version, int) or version < 1:
                    findings.append(f"{packet_id}:{rel}:{job_name} contract_version must be int>=1")
                key = (job_name, int(version)) if isinstance(version, int) else (job_name, -1)
                if key in seen_job_types:
                    findings.append(f"{packet_id}:{rel} duplicate job type/version {job_name}@{version}")
                seen_job_types.add(key)
                for field in ("payload_schema", "checkpoint_schema", "sensitive_field_policy"):
                    if field in job and (not isinstance(job.get(field), str) or not str(job.get(field)).strip()):
                        findings.append(f"{packet_id}:{rel}:{job_name} {field} must be nonempty")
                for field in ("retry_policy", "crash_recovery_policy", "cancellation_policy"):
                    if field in job:
                        value = job.get(field)
                        if not isinstance(value, (dict, str)) or not value:
                            findings.append(f"{packet_id}:{rel}:{job_name} {field} must be nonempty")
                if "coalescing" not in job or not str(job.get("coalescing", "")).strip():
                    findings.append(f"{packet_id}:{rel}:{job_name} missing explicit coalescing policy")

    if findings:
        print(f"SOMA durable job contract closure: HIGH={len(findings)}")
        for finding in findings:
            print(f"[HIGH] {finding}")
        return 1

    print("SOMA durable job contract closure: HIGH=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
