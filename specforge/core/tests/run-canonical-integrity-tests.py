#!/usr/bin/env python3
from pathlib import Path
import hashlib
import importlib.util
import sys
import tempfile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from specforge_project import canonical_artifact_digest

_integrity_spec = importlib.util.spec_from_file_location("specforge_integrity", TOOLS / "specforge-integrity.py")
_integrity = importlib.util.module_from_spec(_integrity_spec)
_integrity_spec.loader.exec_module(_integrity)


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lf = root / "lf.yaml"
        crlf = root / "crlf.yaml"
        cr = root / "cr.yaml"
        changed = root / "changed.yaml"

        logical = "id: PROP-9999-01\nchange: CHG-9999\nrevision: 1\nstatus: awaiting_approval\n"
        lf.write_bytes(logical.encode("utf-8"))
        crlf.write_bytes(logical.replace("\n", "\r\n").encode("utf-8"))
        cr.write_bytes(logical.replace("\n", "\r").encode("utf-8"))
        changed.write_bytes(logical.replace("revision: 1", "revision: 2").encode("utf-8"))

        baseline = canonical_artifact_digest(lf)
        expect(baseline == canonical_artifact_digest(crlf), "CRLF equivalent changed canonical digest")
        expect(baseline == canonical_artifact_digest(cr), "CR equivalent changed canonical digest")
        expect(baseline != canonical_artifact_digest(changed), "material proposal change did not change digest")
        expect(baseline == hashlib.sha256(logical.encode("utf-8")).hexdigest(), "LF canonical digest changed unexpectedly")

        parts = {}
        _integrity.partition_apply(parts, "CHG-9999", "change", "specforge/changes/CHG-9999.yaml", baseline, 1)
        expect(parts, "partition accumulator did not record addition")
        digest = _integrity.registry_digest(parts)
        expect(len(digest) == 64, "partition registry digest is not SHA-256")
        _integrity.partition_apply(parts, "CHG-9999", "change", "specforge/changes/CHG-9999.yaml", baseline, -1)
        expect(parts == {}, "partition accumulator did not reverse exactly")
        probe = _integrity.scale_probe(1_000_000, ["CHG-9999"])
        expect(probe["historical_records_parsed"] == 0 and probe["index_partitions_read"] == 1, "million-scale probe is not delta bounded")

    print("Canonical integrity tests PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
