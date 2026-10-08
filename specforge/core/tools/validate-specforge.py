#!/usr/bin/env python3
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required: pip install pyyaml")
    sys.exit(2)

try:
    import jsonschema
except ImportError:
    print("ERROR: jsonschema is required: pip install jsonschema")
    sys.exit(2)

from specforge_project import (
    canonical_artifact_digest,
    classify_project_path,
    discover_layout,
    iter_record_files,
    load_yaml,
    manifest_core_consistency_blockers,
    read_project_governance_tier_state,
    relative,
    verify_source_revision,
)
from specforge_integration import PROFILE as INTEGRATION_PROFILE, verify_integration_evidence
from specforge_governance_tier import (
    TIER_ORDER,
    GovernanceTierError,
    classify_entries,
    validate_declared_scope,
    verify_policy_archive,
)

parser = argparse.ArgumentParser(description="Validate a SpecForge project")
parser.add_argument("root", nargs="?", default=".")
parser.add_argument("--change", dest="scoped_change")
parser.add_argument("--progress-file")
parser.add_argument("--progress-append", action="store_true")
args = parser.parse_args()

_PROGRESS_STARTED = time.monotonic()
_PROGRESS_PATH = Path(args.progress_file).resolve() if args.progress_file else None
if _PROGRESS_PATH:
    _PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not args.progress_append:
        _PROGRESS_PATH.write_text("", encoding="utf-8")

def emit_progress(phase, processed=None, total=None, substage=None):
    if not _PROGRESS_PATH:
        return
    row = {
        "mode": "full_integrity_v1",
        "phase": phase,
        "processed": processed,
        "total": total,
        "elapsed_seconds": round(time.monotonic() - _PROGRESS_STARTED, 3),
        "substage": substage,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    with _PROGRESS_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    print("SPECFORGE_PROGRESS " + json.dumps(row, sort_keys=True), file=sys.stderr, flush=True)


ROOT = Path(args.root).resolve()
SCOPED_CHANGE_REQUEST = args.scoped_change
errors = []

TYPE_INFO = [
    ("acceptance-criterion", re.compile(r"^AC-\d{4,}-\d{2,}$")),
    ("implementation-attempt", re.compile(r"^IMP-\d{4,}-\d{2,}$")),
    ("impact-analysis", re.compile(r"^IA-\d{4,}-\d{2,}$")),
    ("proposal", re.compile(r"^PROP-\d{4,}-\d{2,}$")),
    ("requirement", re.compile(r"^REQ-\d{4,}$")),
    ("change", re.compile(r"^CHG-\d{4,}$")),
    ("approval", re.compile(r"^APR-\d{4,}$")),
    ("checkpoint", re.compile(r"^CHK-\d{4,}$")),
    ("checkpoint-acceptance-proof", re.compile(r"^CAP-\d{4,}$")),
    ("checkpoint-acceptance", re.compile(r"^ACC-\d{4,}$")),
    ("prospective-finalisation-authority", re.compile(r"^PFA-\d{4,}$")),
    ("reconciliation", re.compile(r"^REC-\d{4,}$")),
    ("decision", re.compile(r"^ADR-\d{4,}$")),
    ("forensic-event", re.compile(r"^EVT-\d{6,}$")),
    ("release", re.compile(r"^REL-\d{4,}$")),
    ("build", re.compile(r"^BLD-\d{4,}$")),
    ("environment", re.compile(r"^ENV-[A-Z0-9_-]+$")),
    ("deployment", re.compile(r"^DEP-\d{4,}$")),
]


def classify_id(value):
    for kind, pattern in TYPE_INFO:
        if pattern.match(str(value)):
            return kind
    return None


try:
    layout = discover_layout(ROOT)
except Exception as exc:
    print("SpecForge validation FAILED")
    print(f" - Project discovery failed: {exc}")
    sys.exit(1)

ROOT = layout.root
manifest = layout.manifest
manifest_path = layout.manifest_path

if layout.mode == "project_format_1":
    if not (ROOT / "specforge" / "SPECFORGE.md").is_file():
        errors.append("Missing required file: specforge/SPECFORGE.md")
    sf = manifest.get("specforge") or {}
    if sf.get("project_format") != 1:
        errors.append(f"Unsupported project_format: {sf.get('project_format')}")
    for key in ("specforge", "project", "specification", "paths", "ownership", "policy"):
        if key not in manifest:
            errors.append(f"Manifest missing key: {key}")
else:
    if not (ROOT / "SPECFORGE.md").is_file():
        errors.append("Missing required file: SPECFORGE.md")
    for key in ("specforge", "project", "specification", "paths", "policy"):
        if key not in manifest:
            errors.append(f"Manifest missing key: {key}")

for name, value in (manifest.get("paths") or {}).items():
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, str):
            continue
        target = (ROOT / item).resolve()
        if not target.exists():
            if name == "packs" and not (manifest.get("packs") or []):
                continue
            if name == "decisions":
                continue
            errors.append(f"Manifest path '{name}' does not exist: {item}")

specification = manifest.get("specification") or {}
for key in ("product_specification", "canonical_data_model"):
    value = specification.get(key)
    if not value and layout.mode != "project_format_1":
        continue
    target = (ROOT / value).resolve() if value else None
    if not target or not target.is_file():
        errors.append(f"Missing authoritative {key}: {value}")

for consistency_blocker in manifest_core_consistency_blockers(layout):
    code = consistency_blocker["code"]
    if code == "core_version_inconsistent":
        errors.append(
            f"Manifest specforge.core_version ({consistency_blocker['declared_core_version']}) does not match "
            f"actually-installed specforge/core/core.yaml's core_version ({consistency_blocker['installed_core_version']})"
        )
    elif code == "data_model_version_inconsistent":
        errors.append(
            f"Manifest specforge.data_model_version ({consistency_blocker['declared_data_model_version']}) does not "
            f"match actually-installed specforge/core/core.yaml's data_model_version ({consistency_blocker['installed_data_model_version']})"
        )
    elif code == "package_core_version_inconsistent":
        errors.append(
            f"specforge/core/package.yaml's declared version ({consistency_blocker['package_version']}) does not "
            f"match actually-installed specforge/core/core.yaml's core_version ({consistency_blocker['installed_core_version']})"
        )
    elif code == "self_referencing_product_specification_inconsistent":
        errors.append(
            f"specification.product_specification self-references a Core product-spec doc embedding version "
            f"{consistency_blocker['embedded_version']}, but declared core_version is "
            f"{consistency_blocker['declared_core_version']} and specification.current_version is "
            f"{consistency_blocker['declared_current_version']} -- all three must agree"
        )
    elif code == "self_referencing_canonical_data_model_inconsistent":
        errors.append(
            f"specification.canonical_data_model self-references a Core canonical-data-model doc embedding version "
            f"{consistency_blocker['embedded_version']}, but declared data_model_version is "
            f"{consistency_blocker['declared_data_model_version']}"
        )

schemas = {}
schema_value = (manifest.get("paths") or {}).get("schemas")
schema_root = (ROOT / schema_value).resolve() if schema_value else (layout.core_root / "schemas")
if schema_root.exists():
    for path in schema_root.glob("*.schema.json"):
        try:
            schemas[path.name.replace(".schema.json", "")] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Cannot parse schema {relative(layout, path)}: {exc}")


# CHG-1054: bounded, validation-only historical evidence compatibility.
HEC_RULES = []
HEC_ROOT = ROOT / "specforge" / "evidence" / "historical-compatibility"


def _hec_normal_rel(value):
    return str(value or "").replace("\\", "/").lstrip("./")


def _hec_first_add_time(rel_path):
    if not (ROOT / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(ROOT), "log", "--diff-filter=A", "--reverse", "--format=%cI", "--", rel_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return dt.datetime.fromisoformat(result.stdout.splitlines()[0].strip().replace("Z", "+00:00"))
    except Exception:
        return None


def _load_hec_rules():
    hec_schema = schemas.get("historical-evidence-compatibility")
    if not HEC_ROOT.exists():
        return
    for registry_path in sorted(HEC_ROOT.glob("HEC-*.yaml")):
        registry_valid = True
        try:
            registry = load_yaml(registry_path)
        except Exception as exc:
            errors.append(f"Cannot parse historical compatibility evidence {relative(layout, registry_path)}: {exc}")
            continue
        if not isinstance(registry, dict):
            errors.append(f"Historical compatibility evidence must be a mapping: {relative(layout, registry_path)}")
            continue
        if hec_schema:
            for exc in jsonschema.Draft202012Validator(hec_schema, format_checker=jsonschema.FormatChecker()).iter_errors(registry):
                location = ".".join(str(x) for x in exc.absolute_path) or "<root>"
                errors.append(f"Historical compatibility schema validation failed for {relative(layout, registry_path)} at {location}: {exc.message}")
                registry_valid = False
        try:
            cutoff = dt.datetime.fromisoformat(str(registry.get("effective_before")).replace("Z", "+00:00"))
            created = dt.datetime.fromisoformat(str(registry.get("created_at")).replace("Z", "+00:00"))
            if cutoff > created:
                errors.append(f"Historical compatibility cutoff follows registry creation in {relative(layout, registry_path)}")
                registry_valid = False
        except Exception:
            cutoff = None
            registry_valid = False
        for rule in registry.get("rules") or []:
            rule_valid = registry_valid and isinstance(rule, dict)
            target = (rule.get("target") or {}) if isinstance(rule, dict) else {}
            rel = _hec_normal_rel(target.get("path"))
            target_path = (ROOT / rel).resolve() if rel else None
            if not target_path:
                rule_valid = False
            else:
                try:
                    target_path.relative_to(ROOT.resolve())
                except ValueError:
                    errors.append(f"Historical compatibility target escapes project: {rel}")
                    rule_valid = False
                if not target_path.is_file():
                    errors.append(f"Historical compatibility target missing: {rel}")
                    rule_valid = False
                elif canonical_artifact_digest(target_path) != target.get("sha256"):
                    errors.append(f"Historical compatibility target digest mismatch: {rel}")
                    rule_valid = False
            if rule.get("status") in ("active", "active_with_notes"):
                first_seen = _hec_first_add_time(rel)
                if cutoff is None or first_seen is None or first_seen > cutoff:
                    errors.append(f"Historical compatibility target is not historical before cutoff: {rel}")
                    rule_valid = False
            HEC_RULES.append({"registry": registry, "rule": rule, "valid": rule_valid, "path": registry_path})


def _hec_active_rule(issue, path, target_id=None):
    rel = _hec_normal_rel(relative(layout, Path(path)))
    for entry in HEC_RULES:
        rule = entry.get("rule") or {}
        target = rule.get("target") or {}
        if not entry.get("valid") or rule.get("status") != "active" or rule.get("issue") != issue:
            continue
        if _hec_normal_rel(target.get("path")) != rel:
            continue
        if target_id is not None and str(target.get("id") or "") != str(target_id):
            continue
        return entry
    return None


def _hec_legacy_proposal_scope_compatible(path, data, exc):
    if exc.validator != "enum" or exc.instance != "create":
        return False
    location = list(exc.absolute_path)
    if len(location) != 3 or location[0] != "declared_scope" or location[2] != "operation":
        return False
    entry = _hec_active_rule("legacy_proposal_scope_create", path, data.get("id"))
    if not entry:
        return False
    evidence = entry["rule"].get("evidence") or {}
    expected = set(_hec_normal_rel(p) for p in (evidence.get("expected_absent_paths") or []))
    creates = {
        _hec_normal_rel(item.get("path"))
        for item in (data.get("declared_scope") or [])
        if isinstance(item, dict) and item.get("operation") == "create"
    }
    try:
        scope_item = (data.get("declared_scope") or [])[int(location[1])]
    except Exception:
        return False
    if not expected or creates != expected or _hec_normal_rel(scope_item.get("path")) not in expected:
        return False
    baseline = str(evidence.get("baseline_revision") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", baseline):
        return False
    for expected_path in expected:
        found = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{baseline}:{expected_path}"],
            capture_output=True,
            text=True,
        )
        if found.returncode == 0:
            return False
    return evidence.get("verified_absent") is True


def _hec_legacy_approval_proof_compatible(proof_path, proof, approval, proposal_digest):
    presentation = proof.get("presentation") if isinstance(proof, dict) else None
    entry = _hec_active_rule("legacy_approval_proof_missing_type", proof_path, presentation)
    if not entry or not isinstance(proof, dict) or "type" in proof:
        return False
    rule_evidence = entry["rule"].get("evidence") or {}
    if rule_evidence.get("approval") != approval.get("id") or rule_evidence.get("proposal") != approval.get("proposal"):
        return False
    if rule_evidence.get("expected_missing_field") != "type" or rule_evidence.get("expected_type_value") != "informed_approval_proof":
        return False
    approval_evidence = approval.get("evidence") or {}
    approval_scope = approval.get("scope") or {}
    for bound in (approval_evidence.get("proposal_digest"), approval_scope.get("proposal_sha256")):
        if bound and bound != proposal_digest:
            return False
    return (
        proof.get("proposal") == approval.get("proposal")
        and proof.get("proposal_digest") == proposal_digest
        and proof.get("change") == approval.get("change")
        and proof.get("decision") == approval.get("decision")
        and proof.get("received_at") == approval.get("timestamp")
        and (proof.get("actor") or {}).get("type") == "human"
        and (proof.get("actor") or {}).get("id") == (approval.get("actor") or {}).get("id")
    )


def _approval_proof_binding_valid(approval, proposal_rec):
    if not proposal_rec:
        return False
    proof_rel = (approval.get("evidence") or {}).get("informed_approval_proof")
    if not proof_rel:
        return False
    proof_path = (ROOT / str(proof_rel)).resolve()
    try:
        proof_path.relative_to(ROOT.resolve())
    except ValueError:
        return False
    if not proof_path.is_file():
        return False
    try:
        proof = load_yaml(proof_path)
    except Exception:
        return False
    if not isinstance(proof, dict):
        return False
    proposal_digest = canonical_artifact_digest(proposal_rec["file"])
    strict = (
        proof.get("type") == "informed_approval_proof"
        and proof.get("proposal") == approval.get("proposal")
        and proof.get("proposal_digest") == proposal_digest
        and proof.get("decision") == approval.get("decision")
        and proof.get("received_at") == approval.get("timestamp")
        and (proof.get("actor") or {}).get("type") == "human"
        and (proof.get("actor") or {}).get("id") == (approval.get("actor") or {}).get("id")
    )
    return strict or _hec_legacy_approval_proof_compatible(proof_path, proof, approval, proposal_digest)


def _hec_checkpoint_chronology_compatible(owner, proof, checkpoint_rec):
    cap_path = ROOT / owner
    rel = _hec_normal_rel(relative(layout, cap_path))
    entry = None
    for candidate in HEC_RULES:
        rule = candidate.get("rule") or {}
        target = rule.get("target") or {}
        if not candidate.get("valid") or rule.get("issue") != "checkpoint_creation_chronology":
            continue
        if rule.get("status") not in ("active", "active_with_notes"):
            continue
        if _hec_normal_rel(target.get("path")) != rel or str(target.get("id") or "") != str(proof.get("id") or ""):
            continue
        entry = candidate
        break
    if not entry or not checkpoint_rec:
        return False
    rule = entry["rule"]
    evidence = rule.get("evidence") or {}
    if evidence.get("checkpoint") != proof.get("checkpoint"):
        return False
    checkpoint_path = _hec_normal_rel(evidence.get("checkpoint_path"))
    if checkpoint_path != checkpoint_rec.get("path"):
        return False
    if evidence.get("checkpoint_sha256") != canonical_artifact_digest(checkpoint_rec["file"]):
        return False
    if checkpoint_rec["data"].get("candidate", {}).get("material") != proof.get("candidate", {}).get("material"):
        return False
    if checkpoint_rec["data"].get("included_changes_digest") != proof.get("included_changes_digest"):
        return False
    if evidence.get("presented_at") != proof.get("presented_at"):
        return False
    if (proof.get("actor") or {}).get("type") != "human":
        return False
    try:
        presented_at = dt.datetime.fromisoformat(str(proof.get("presented_at")).replace("Z", "+00:00"))
        received_at = dt.datetime.fromisoformat(str(proof.get("received_at")).replace("Z", "+00:00"))
    except Exception:
        return False
    if received_at < presented_at:
        return False

    if rule.get("status") == "active":
        commit = str(evidence.get("provider_commit") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            return False
        show = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{checkpoint_path}"], capture_output=True)
        if show.returncode != 0:
            return False
        historical = hashlib.sha256(show.stdout.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()
        if historical != evidence.get("checkpoint_sha256"):
            return False
        stamp = subprocess.run(["git", "-C", str(ROOT), "show", "-s", "--format=%cI", commit], capture_output=True, text=True)
        if stamp.returncode != 0:
            return False
        try:
            commit_time = dt.datetime.fromisoformat(stamp.stdout.strip().replace("Z", "+00:00"))
        except Exception:
            return False
        return commit_time <= presented_at

    allow_key = (rule.get("id"), proof.get("id"), proof.get("checkpoint"))
    if allow_key != ("HEC-0001-R04", "CAP-0006", "CHK-0016"):
        return False
    notes = str(rule.get("notes") or "")
    if "ALLOW WITH NOTES" not in notes or "cannot now be reconstructed" not in notes:
        return False
    if evidence.get("checkpoint_created_at") is not None:
        return False
    if evidence.get("chronology_disposition") != "indeterminate_historical":
        return False
    if evidence.get("earlier_qualifying_provider_evidence_found") is not False:
        return False
    if evidence.get("contradictory_provider_evidence_found") is not False:
        return False
    first_commit = str(evidence.get("current_lineage_first_add_commit") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", first_commit):
        return False
    show = subprocess.run(["git", "-C", str(ROOT), "show", f"{first_commit}:{checkpoint_path}"], capture_output=True)
    if show.returncode != 0:
        return False
    historical = hashlib.sha256(show.stdout.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()
    if historical != evidence.get("checkpoint_sha256"):
        return False
    stamp = subprocess.run(["git", "-C", str(ROOT), "show", "-s", "--format=%cI", first_commit], capture_output=True, text=True)
    if stamp.returncode != 0:
        return False
    try:
        first_commit_time = dt.datetime.fromisoformat(stamp.stdout.strip().replace("Z", "+00:00"))
        recorded_first_time = dt.datetime.fromisoformat(str(evidence.get("current_lineage_first_add_time")).replace("Z", "+00:00"))
    except Exception:
        return False
    if first_commit_time != recorded_first_time or first_commit_time <= presented_at:
        return False
    return True


_load_hec_rules()

records = {}
by_kind = {}
record_paths = list(iter_record_files(layout))
emit_progress("record_schema_validation", 0, len(record_paths), "loading and schema-validating canonical records")
for _record_index, path in enumerate(record_paths, start=1):
    try:
        data = load_yaml(path)
    except Exception as exc:
        errors.append(f"Cannot parse {relative(layout, path)}: {exc}")
        continue
    if not isinstance(data, dict) or not data.get("id"):
        continue
    rid = str(data["id"])
    kind = classify_id(rid)
    if not kind:
        errors.append(f"Unrecognised canonical id {rid} in {relative(layout, path)}")
        continue
    if rid in records:
        errors.append(f"Duplicate canonical id {rid}: {records[rid]['path']} and {relative(layout, path)}")
        continue
    records[rid] = {"kind": kind, "data": data, "path": relative(layout, path), "file": path}
    by_kind.setdefault(kind, {})[rid] = data
    schema = schemas.get(kind)
    if schema:
        for exc in jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).iter_errors(data):
            if kind == "proposal" and _hec_legacy_proposal_scope_compatible(path, data, exc):
                continue
            location = ".".join(str(x) for x in exc.absolute_path) or "<root>"
            errors.append(f"Schema validation failed for {relative(layout, path)} at {location}: {exc.message}")
    if _record_index == len(record_paths) or _record_index % 100 == 0:
        emit_progress("record_schema_validation", _record_index, len(record_paths), "loading and schema-validating canonical records")

emit_progress("reference_validation", 0, len(records), "checking canonical references")

def scoped_change_closure(change_id):
    if not change_id:
        return None
    target = records.get(str(change_id))
    if not target or target["kind"] != "change":
        errors.append(f"Scoped validation target missing or not a change: {change_id}")
        return set()

    closure = set()
    pending = [str(change_id)]
    while pending:
        current = pending.pop()
        if current in closure:
            continue
        rec = records.get(current)
        if not rec or rec["kind"] != "change":
            errors.append(f"Scoped validation dependency missing or not a change: {current}")
            continue
        closure.add(current)
        relationships = rec["data"].get("relationships") or {}
        for dependency in relationships.get("depends_on") or []:
            dependency = str(dependency)
            dep_rec = records.get(dependency)
            if not dep_rec or dep_rec["kind"] != "change":
                errors.append(
                    f"Scoped validation dependency missing or not a change: {current} -> {dependency}"
                )
                continue
            if dependency not in closure:
                pending.append(dependency)
    return closure


SCOPED_CHANGE_IDS = scoped_change_closure(SCOPED_CHANGE_REQUEST)
VALIDATION_MODE = "change_scoped" if SCOPED_CHANGE_REQUEST else "full"


def exists(rid, kind=None):
    rec = records.get(rid)
    return bool(rec and (kind is None or rec["kind"] == kind))


def require_ref(owner, field, rid, kind=None):
    if rid is None:
        return
    if not exists(str(rid), kind):
        suffix = f" ({kind})" if kind else ""
        errors.append(f"Broken reference in {owner}: {field} -> {rid}{suffix}")


for rid, rec in records.items():
    d, kind, owner = rec["data"], rec["kind"], rec["path"]
    if kind == "requirement":
        intro = d.get("introduced") or {}
        require_ref(owner, "introduced.by_change", intro.get("by_change"), "change")
        for ac in d.get("acceptance_criteria") or []:
            require_ref(owner, "acceptance_criteria", ac, "acceptance-criterion")
    elif kind == "acceptance-criterion":
        require_ref(owner, "requirement", d.get("requirement"), "requirement")
    elif kind == "impact-analysis":
        require_ref(owner, "change", d.get("change"), "change")
    elif kind == "proposal":
        require_ref(owner, "change", d.get("change"), "change")
        for ia in d.get("based_on_impact_analysis") or []:
            require_ref(owner, "based_on_impact_analysis", ia, "impact-analysis")
        for approval in d.get("approvals") or []:
            require_ref(owner, "approvals", approval, "approval")
        binding=d.get("project_definition_reconciliation") or {}
        if binding:
            mode=binding.get("mode")
            version=str(d.get("proposed_specification_version") or "")
            match=re.search(r"-alpha\.(\d+)$",version)
            revision=int(match.group(1)) if match else None
            if mode is None and revision is not None and revision>=26:
                errors.append(f"project-definition reconciliation mode missing in new proposal {owner}")
            elif mode is not None and mode not in ("context_only","durable_update"):
                errors.append(f"unknown project-definition reconciliation mode in {owner}: {mode}")
            else:
                effective_mode=mode or "durable_update"
                definition_path=str(binding.get("path") or "").replace("\\","/").lstrip("./")
                scope=set()
                for scope_item in d.get("declared_scope") or []:
                    if not isinstance(scope_item,dict): continue
                    for key in ("path","to"):
                        value=scope_item.get(key)
                        if isinstance(value,str) and value.strip(): scope.add(value.strip().replace("\\","/").lstrip("./"))
                if effective_mode=="context_only" and definition_path in scope:
                    errors.append(f"context_only proposal includes project definition in implementation scope: {owner}")
                if effective_mode=="durable_update" and definition_path and definition_path not in scope:
                    errors.append(f"durable_update proposal omits project definition from implementation scope: {owner}")
    elif kind == "approval":
        require_ref(owner, "change", d.get("change"), "change")
        require_ref(owner, "proposal", d.get("proposal"), "proposal")
        proposal = records.get(str(d.get("proposal")))
        if proposal and proposal["data"].get("change") != d.get("change"):
            errors.append(f"Approval/change mismatch in {owner}: proposal {d.get('proposal')} belongs to {proposal['data'].get('change')}")
        change_rec = records.get(str(d.get("change")))
        if change_rec and (change_rec["data"].get("governance") or {}).get("lifecycle_enforcement") == "controlled_v3":
            evidence = d.get("evidence") or {}
            proof_rel = evidence.get("informed_approval_proof")
            proof = None
            if not proof_rel:
                errors.append(f"controlled_v3 approval missing informed approval proof in {owner}")
            else:
                proof_path = (layout.root / str(proof_rel)).resolve()
                try:
                    proof_path.relative_to(layout.root.resolve())
                except ValueError:
                    errors.append(f"controlled_v3 approval proof escapes project in {owner}")
                else:
                    if not proof_path.is_file():
                        errors.append(f"controlled_v3 approval proof missing in {owner}")
                    else:
                        try:
                            proof = load_yaml(proof_path)
                        except Exception:
                            proof = None
                        if not isinstance(proof, dict):
                            errors.append(f"controlled_v3 approval proof invalid in {owner}")
            if isinstance(proof, dict):
                proposal_digest = canonical_artifact_digest(proposal["file"]) if proposal else None
                proposal_binding_mismatch = (
                    proof.get("type") != "informed_approval_proof"
                    or proof.get("proposal") != d.get("proposal")
                    or proof.get("proposal_digest") != proposal_digest
                )
                if proposal_binding_mismatch and not _hec_legacy_approval_proof_compatible(proof_path, proof, d, proposal_digest):
                    errors.append(f"controlled_v3 approval proof proposal binding mismatch in {owner}")
                if proof.get("decision") != d.get("decision") or proof.get("received_at") != d.get("timestamp"):
                    errors.append(f"controlled_v3 approval proof chronology mismatch in {owner}")
                if (proof.get("actor") or {}).get("type") != "human" or (proof.get("actor") or {}).get("id") != (d.get("actor") or {}).get("id"):
                    errors.append(f"controlled_v3 approval proof actor mismatch in {owner}")
    elif kind == "implementation-attempt":
        require_ref(owner, "change", d.get("change"), "change")
        require_ref(owner, "proposal", d.get("proposal"), "proposal")
    elif kind == "change":
        ia = (d.get("impact_analysis") or {}).get("current")
        prop = (d.get("proposal") or {}).get("current")
        require_ref(owner, "impact_analysis.current", ia, "impact-analysis")
        require_ref(owner, "proposal.current", prop, "proposal")
        for approval in d.get("approvals") or []:
            require_ref(owner, "approvals", approval, "approval")
        for imp in ((d.get("implementation") or {}).get("attempts") or []):
            require_ref(owner, "implementation.attempts", imp, "implementation-attempt")
        completed = (d.get("release") or {}).get("completed_in")
        if completed:
            require_ref(owner, "release.completed_in", completed, "release")
    elif kind == "checkpoint":
        for change in d.get("included_changes") or []:
            require_ref(owner, "included_changes", change, "change")
        acceptance = (d.get("acceptance") or {}).get("current")
        if acceptance:
            require_ref(owner, "acceptance.current", acceptance, "checkpoint-acceptance")
    elif kind == "checkpoint-acceptance-proof":
        require_ref(owner, "checkpoint", d.get("checkpoint"), "checkpoint")
        checkpoint_rec = records.get(str(d.get("checkpoint")))
        if (d.get("actor") or {}).get("type") != "human":
            errors.append(f"Checkpoint acceptance proof requires human actor in {owner}")
        if checkpoint_rec:
            expected_digest = checkpoint_rec["data"].get("included_changes_digest")
            expected_material = ((checkpoint_rec["data"].get("candidate") or {}).get("material") or {})
            actual_material = ((d.get("candidate") or {}).get("material") or {})
            if d.get("included_changes_digest") != expected_digest:
                errors.append(f"Checkpoint acceptance proof/change-set mismatch in {owner}")
            if actual_material.get("revision") != expected_material.get("revision") or actual_material.get("file_count") != expected_material.get("file_count"):
                errors.append(f"Checkpoint acceptance proof/candidate mismatch in {owner}")
            try:
                created_at = dt.datetime.fromisoformat(str((checkpoint_rec["data"].get("metadata") or {}).get("created_at")).replace("Z", "+00:00"))
                presented_at = dt.datetime.fromisoformat(str(d.get("presented_at")).replace("Z", "+00:00"))
                received_at = dt.datetime.fromisoformat(str(d.get("received_at")).replace("Z", "+00:00"))
                if presented_at < created_at:
                    errors.append(f"Checkpoint acceptance proof presentation predates checkpoint in {owner}")
                if received_at < presented_at:
                    errors.append(f"Checkpoint acceptance proof predates presentation in {owner}")
            except Exception:
                if not _hec_checkpoint_chronology_compatible(owner, d, checkpoint_rec):
                    errors.append(f"Checkpoint acceptance proof chronology invalid in {owner}")
        presentation_rel = d.get("presentation")
        if not presentation_rel:
            errors.append(f"Checkpoint acceptance proof presentation missing in {owner}")
        else:
            presentation_path = (layout.root / str(presentation_rel)).resolve()
            if not presentation_path.is_file():
                errors.append(f"Checkpoint acceptance proof presentation record missing in {owner}")
            else:
                try:
                    presentation = load_yaml(presentation_path)
                except Exception:
                    presentation = {}
                if presentation.get("checkpoint") != d.get("checkpoint") or presentation.get("session") != d.get("session") or presentation.get("presented_at") != d.get("presented_at"):
                    errors.append(f"Checkpoint acceptance proof presentation binding mismatch in {owner}")
    elif kind == "checkpoint-acceptance":
        require_ref(owner, "checkpoint", d.get("checkpoint"), "checkpoint")
        checkpoint_rec = records.get(str(d.get("checkpoint")))
        if checkpoint_rec:
            expected = checkpoint_rec["data"].get("included_changes_digest")
            if expected and d.get("included_changes_digest") != expected:
                errors.append(f"Checkpoint acceptance/change-set mismatch in {owner}")
            expected_material = ((checkpoint_rec["data"].get("candidate") or {}).get("material") or {}).get("revision")
            actual_material = ((d.get("candidate") or {}).get("material") or {}).get("revision")
            if expected_material and actual_material != expected_material:
                errors.append(f"Checkpoint acceptance/candidate mismatch in {owner}")
        authority = d.get("authority") or {}
        if authority.get("mode") == "prospective_exact_candidate_v1":
            source = authority.get("source")
            require_ref(owner, "authority.source", source, "prospective-finalisation-authority")
            pfa_rec = records.get(str(source))
            if (d.get("actor") or {}).get("type") != "automated_system":
                errors.append(f"Prospective checkpoint acceptance actor invalid in {owner}")
            mechanism = d.get("mechanism") or {}
            if mechanism.get("type") != "prospective_finalisation_authority" or mechanism.get("reference") != source:
                errors.append(f"Prospective checkpoint acceptance provenance invalid in {owner}")
            if pfa_rec:
                pfa = pfa_rec["data"]; projected = pfa.get("projected_candidate") or {}; actual = ((d.get("candidate") or {}).get("material") or {})
                if actual.get("revision") != projected.get("revision") or actual.get("file_count") != projected.get("file_count"):
                    errors.append(f"Prospective checkpoint acceptance candidate mismatch in {owner}")
                if checkpoint_rec and (checkpoint_rec["data"].get("included_changes") or []) != [pfa.get("change")]:
                    errors.append(f"Prospective checkpoint acceptance change-set mismatch in {owner}")
                try:
                    accepted_at = dt.datetime.fromisoformat(str(d.get("timestamp")).replace("Z", "+00:00"))
                    granted_at = dt.datetime.fromisoformat(str(pfa.get("timestamp")).replace("Z", "+00:00"))
                    created_at = dt.datetime.fromisoformat(str((checkpoint_rec["data"].get("metadata") or {}).get("created_at")).replace("Z", "+00:00")) if checkpoint_rec else None
                    if accepted_at < granted_at: errors.append(f"Prospective checkpoint acceptance predates its authority in {owner}")
                    if created_at is not None and accepted_at < created_at: errors.append(f"Prospective checkpoint acceptance predates checkpoint creation in {owner}")
                except Exception:
                    errors.append(f"Prospective checkpoint acceptance chronology invalid in {owner}")
        elif authority.get("mode") == "direct_checkpoint_acceptance_v1":
            source = authority.get("source")
            require_ref(owner, "authority.source", source, "checkpoint-acceptance-proof")
            cap_rec = records.get(str(source))
            if (d.get("actor") or {}).get("type") != "human":
                errors.append(f"Direct checkpoint acceptance actor invalid in {owner}")
            mechanism = d.get("mechanism") or {}
            if mechanism.get("type") != "checkpoint_acceptance_proof" or mechanism.get("reference") != source:
                errors.append(f"Direct checkpoint acceptance provenance invalid in {owner}")
            if cap_rec:
                cap = cap_rec["data"]
                if cap.get("checkpoint") != d.get("checkpoint"):
                    errors.append(f"Direct checkpoint acceptance checkpoint mismatch in {owner}")
                if d.get("timestamp") != cap.get("received_at"):
                    errors.append(f"Direct checkpoint acceptance timestamp mismatch in {owner}")
                if (d.get("actor") or {}).get("id") != (cap.get("actor") or {}).get("id"):
                    errors.append(f"Direct checkpoint acceptance actor/proof mismatch in {owner}")
                actual = ((d.get("candidate") or {}).get("material") or {})
                bound = ((cap.get("candidate") or {}).get("material") or {})
                if actual.get("revision") != bound.get("revision") or actual.get("file_count") != bound.get("file_count"):
                    errors.append(f"Direct checkpoint acceptance candidate/proof mismatch in {owner}")
    elif kind == "prospective-finalisation-authority":
        require_ref(owner, "change", d.get("change"), "change")
        require_ref(owner, "proposal", d.get("proposal"), "proposal")
        proposal_rec = records.get(str(d.get("proposal")))
        if proposal_rec:
            if proposal_rec["data"].get("change") != d.get("change"):
                errors.append(f"Prospective finalisation authority/change mismatch in {owner}")
            if canonical_artifact_digest(proposal_rec["file"]) != d.get("proposal_digest"):
                errors.append(f"Prospective finalisation authority/proposal digest mismatch in {owner}")
        if (d.get("actor") or {}).get("type") != "human":
            errors.append(f"Prospective finalisation authority requires human principal in {owner}")
        if ((d.get("scope") or {}).get("change_set") or []) != [d.get("change")]:
            errors.append(f"Prospective finalisation authority must contain exactly its governed change in {owner}")
    elif kind == "reconciliation":
        supersedes = d.get("supersedes")
        if supersedes:
            require_ref(owner, "supersedes", supersedes, "reconciliation")
        adoption = d.get("adoption") or {}
        if adoption.get("change"):
            require_ref(owner, "adoption.change", adoption.get("change"), "change")
        if adoption.get("proposal"):
            require_ref(owner, "adoption.proposal", adoption.get("proposal"), "proposal")
        bookkeeping = d.get("authority_bookkeeping") or {}
        if bookkeeping.get("checkpoint"):
            require_ref(owner, "authority_bookkeeping.checkpoint", bookkeeping.get("checkpoint"), "checkpoint")
        if bookkeeping.get("acceptance"):
            require_ref(owner, "authority_bookkeeping.acceptance", bookkeeping.get("acceptance"), "checkpoint-acceptance")
    elif kind == "release":
        for change in d.get("changes") or []:
            require_ref(owner, "changes", change, "change")
        build = (d.get("build") or {}).get("id")
        if build:
            require_ref(owner, "build.id", build, "build")
        for dep in d.get("deployments") or []:
            require_ref(owner, "deployments", dep, "deployment")
    elif kind == "deployment":
        require_ref(owner, "release", d.get("release"), "release")
        require_ref(owner, "environment", d.get("environment"), "environment")
        build = (d.get("build") or {}).get("id")
        if build:
            require_ref(owner, "build.id", build, "build")

emit_progress("reference_validation", len(records), len(records), "canonical reference pass complete")
emit_progress("lifecycle_validation", 0, len(records), "checking lifecycle and approval invariants")
for rid, rec in records.items():
    if rec["kind"] == "proposal":
        if not rid.startswith("PROP-" + str(rec["data"].get("change")).split("-")[-1] + "-"):
            errors.append(f"Proposal ID/change mismatch in {rec['path']}: {rid} vs {rec['data'].get('change')}")
    elif rec["kind"] == "impact-analysis":
        if not rid.startswith("IA-" + str(rec["data"].get("change")).split("-")[-1] + "-"):
            errors.append(f"Impact-analysis ID/change mismatch in {rec['path']}: {rid} vs {rec['data'].get('change')}")

_lifecycle_total = len(records)
_lifecycle_step = max(1, (_lifecycle_total + 19) // 20)
_lifecycle_started_change = False
for _lifecycle_index, (rid, rec) in enumerate(records.items(), start=1):
    _lifecycle_processed = _lifecycle_index - 1
    if _lifecycle_processed and _lifecycle_processed % _lifecycle_step == 0:
        emit_progress(
            "lifecycle_validation",
            _lifecycle_processed,
            _lifecycle_total,
            "checking lifecycle and approval invariants",
        )
    if rec["kind"] != "change":
        continue
    if not _lifecycle_started_change:
        emit_progress(
            "lifecycle_validation",
            _lifecycle_index,
            _lifecycle_total,
            f"checking governed change {rid}",
        )
        _lifecycle_started_change = True
    d = rec["data"]
    if (d.get("governance") or {}).get("lifecycle_enforcement") not in ("controlled_v1", "controlled_v2", "controlled_v3"):
        continue
    proposal_id = (d.get("proposal") or {}).get("current")
    valid_approval = False
    proposal_rec = records.get(str(proposal_id))
    if proposal_rec:
        actual = canonical_artifact_digest(proposal_rec["file"])
        for approval_id in d.get("approvals") or []:
            approval_rec = records.get(str(approval_id))
            if not approval_rec:
                continue
            approval = approval_rec["data"]
            if approval.get("decision") != "approved" or approval.get("proposal") != proposal_id:
                continue
            if (approval.get("actor") or {}).get("type") != "human":
                continue
            expected = (approval.get("evidence") or {}).get("proposal_digest") or (approval.get("scope") or {}).get("proposal_sha256")
            if expected and expected == actual:
                valid_approval = True
                break
    if d.get("status") in {"approved", "in_progress", "implemented", "validated", "ready_for_checkpoint", "completed"} and not valid_approval:
        errors.append(f"Lifecycle gate violation in {rec['path']}: valid exact human approval missing")
    if (d.get("governance") or {}).get("lifecycle_enforcement") == "controlled_v3" and valid_approval:
        current_proposal_id = (d.get("proposal") or {}).get("current")
        for attempt_id in ((d.get("implementation") or {}).get("attempts") or []):
            attempt_rec = records.get(str(attempt_id))
            if not attempt_rec:
                continue
            attempt = attempt_rec["data"]
            attempt_proposal_id = attempt.get("proposal") or current_proposal_id
            attempt_proposal_rec = records.get(str(attempt_proposal_id))
            approval_time = None
            if attempt_proposal_rec:
                proposal_digest = canonical_artifact_digest(attempt_proposal_rec["file"])
                for approval_id in d.get("approvals") or []:
                    approval_rec = records.get(str(approval_id))
                    if not approval_rec:
                        continue
                    approval = approval_rec["data"]
                    expected = (approval.get("evidence") or {}).get("proposal_digest") or (approval.get("scope") or {}).get("proposal_sha256")
                    if (
                        approval.get("decision") == "approved"
                        and approval.get("proposal") == attempt_proposal_id
                        and (approval.get("actor") or {}).get("type") == "human"
                        and expected == proposal_digest
                        and _approval_proof_binding_valid(approval, attempt_proposal_rec)
                    ):
                        try:
                            approval_time = dt.datetime.fromisoformat(str(approval.get("timestamp")).replace("Z", "+00:00"))
                        except Exception:
                            approval_time = None
                        break
            try:
                started_at = dt.datetime.fromisoformat(str(attempt.get("started_at")).replace("Z", "+00:00"))
            except Exception:
                started_at = None
            if approval_time is None or started_at is None:
                errors.append(f"controlled_v3 implementation chronology missing in {attempt_rec['path']}")
            elif started_at < approval_time:
                errors.append(f"controlled_v3 implementation predates approval in {attempt_rec['path']}")
    if d.get("status") == "completed" and (SCOPED_CHANGE_IDS is None or rid in SCOPED_CHANGE_IDS):
        supported = False
        revision_failures = []
        for attempt_id in ((d.get("implementation") or {}).get("attempts") or []):
            attempt_rec = records.get(str(attempt_id))
            if not attempt_rec:
                continue
            attempt = attempt_rec["data"]
            checks = attempt.get("validation_checks") or []
            required = [check for check in checks if check.get("required")]
            tests = attempt.get("tests") or {}
            tests_passed = tests.get("status") == "passed" or (bool(tests.get("passed")) and not tests.get("failed"))
            if not (
                attempt.get("outcome") == "passed"
                and required
                and all(check.get("status") == "passed" for check in required)
                and tests_passed
            ):
                continue
            integration = attempt.get("integration") or {}
            if integration.get("profile") == INTEGRATION_PROFILE:
                revision = verify_integration_evidence(layout, attempt, mode="static")
            else:
                revision = verify_source_revision(
                    layout,
                    attempt.get("source_revision") or {},
                    mode="static",
                    require_provider=False,
                )
            if revision.get("valid"):
                supported = True
                break
            revision_failures += revision.get("blockers") or []
        if not supported:
            detail = ", ".join(sorted(set(revision_failures))) if revision_failures else "missing immutable source/integration revision evidence"
            errors.append(
                f"Lifecycle gate violation in {rec['path']}: completion lacks passing implementation, mandatory validation/test evidence, or verifiable material revision ({detail})"
            )

emit_progress("lifecycle_validation", len(records), len(records), "primary lifecycle pass complete")
emit_progress("authority_replay_validation", 0, None, "checking checkpoint authority and replay protection")
# CHG-1034: controlled_v3 checkpoint acceptance must have independent direct CAP authority or a valid PFA.
for _rid, _rec in records.items():
    if _rec["kind"] != "checkpoint" or _rec["data"].get("status") != "accepted":
        continue
    _changes = _rec["data"].get("included_changes") or []
    _v3 = [
        cid for cid in _changes
        if cid in records and (records[cid]["data"].get("governance") or {}).get("lifecycle_enforcement") == "controlled_v3"
    ]
    if not _v3:
        continue
    _acc_id = (_rec["data"].get("acceptance") or {}).get("current")
    _acc = records.get(str(_acc_id))
    if not _acc or _acc["kind"] != "checkpoint-acceptance":
        errors.append(f"controlled_v3 checkpoint {_rid} missing canonical acceptance")
        continue
    _mode = ((_acc["data"].get("authority") or {}).get("mode"))
    if _mode not in ("direct_checkpoint_acceptance_v1", "prospective_exact_candidate_v1"):
        errors.append(f"controlled_v3 checkpoint {_rid} acceptance lacks independent CAP or PFA authority")

# CHG-1033: prospective authority is single-use.
_pfa_consumers = {}
for _rid, _rec in records.items():
    if _rec["kind"] != "checkpoint-acceptance": continue
    _authority = _rec["data"].get("authority") or {}
    if _authority.get("mode") != "prospective_exact_candidate_v1": continue
    _source = _authority.get("source")
    if _source: _pfa_consumers.setdefault(str(_source), []).append(_rid)
for _source, _consumers in _pfa_consumers.items():
    if len(_consumers) > 1:
        errors.append(f"Prospective finalisation authority replay detected: {_source} consumed by " + ", ".join(sorted(_consumers)))

# CHG-1034: checkpoint acceptance proof is single-use.
_cap_consumers = {}
for _rid, _rec in records.items():
    if _rec["kind"] != "checkpoint-acceptance":
        continue
    _authority = _rec["data"].get("authority") or {}
    if _authority.get("mode") != "direct_checkpoint_acceptance_v1":
        continue
    _source = _authority.get("source")
    if _source:
        _cap_consumers.setdefault(str(_source), []).append(_rid)
for _source, _consumers in _cap_consumers.items():
    if len(_consumers) > 1:
        errors.append(f"Checkpoint acceptance proof replay detected: {_source} consumed by " + ", ".join(sorted(_consumers)))

governance_tier_state = read_project_governance_tier_state(layout)
if governance_tier_state["status"] == "corrupted":
    errors.append(
        "Governance-tier activation state is corrupted: specforge/project.yaml's governance_tier fields and "
        "specforge/evidence/governance-tier-grandfather.yaml are inconsistent (missing, digest mismatch, or an "
        "unrecognised enforcement profile) rather than cleanly not-activated or validly active"
    )

emit_progress("governance_policy_validation", 0, None, "checking governance policy and tier consistency")
policy_archive_root = (layout.root / (layout.manifest.get("paths") or {}).get("evidence", "specforge/evidence")).resolve() / "governance-tier-policy"
if policy_archive_root.is_dir():
    for archive_path in sorted(policy_archive_root.glob("*.yaml")):
        claimed = archive_path.stem
        actual = canonical_artifact_digest(archive_path)
        if actual != claimed:
            errors.append(
                f"Governance-tier policy archive digest mismatch: {relative(layout, archive_path)} claims "
                f"{claimed} but its actual content digest is {actual}"
            )

POST_APPROVAL_STATES = {"approved", "in_progress", "implemented", "validated", "ready_for_checkpoint", "completed"}
for rid, rec in records.items():
    if rec["kind"] != "change":
        continue
    d = rec["data"]
    declared_profile = (d.get("governance") or {}).get("lifecycle_enforcement")
    if declared_profile not in ("controlled_v1", "controlled_v2"):
        continue
    if d.get("status") not in POST_APPROVAL_STATES:
        continue
    if governance_tier_state["status"] == "corrupted":
        continue

    proposal_id = (d.get("proposal") or {}).get("current")
    proposal_rec = records.get(str(proposal_id))
    proposal_digest = canonical_artifact_digest(proposal_rec["file"]) if proposal_rec else None
    grandfathered = (
        governance_tier_state["status"] == "active"
        and proposal_digest is not None
        and proposal_digest in governance_tier_state["grandfather_digests"]
    )

    if not grandfathered and declared_profile != governance_tier_state["effective_lifecycle_profile"]:
        errors.append(
            f"Governance-tier profile mismatch in {rec['path']}: declares {declared_profile} but the project's "
            f"effective lifecycle profile is {governance_tier_state['effective_lifecycle_profile']} and this "
            f"change's exact current proposal digest is not present in the verified grandfather evidence"
        )
        continue

    if declared_profile != "controlled_v2" or grandfathered:
        continue
    if not proposal_rec:
        continue

    proposal_data = proposal_rec["data"]
    governance_tier = proposal_data.get("governance_tier") or {}
    requested = governance_tier.get("requested")
    policy_digest = governance_tier.get("policy_digest")

    valid_approval = False
    for approval_id in d.get("approvals") or []:
        approval_rec = records.get(str(approval_id))
        if not approval_rec:
            continue
        approval = approval_rec["data"]
        if approval.get("decision") != "approved" or approval.get("proposal") != proposal_id:
            continue
        if (approval.get("actor") or {}).get("type") != "human":
            continue
        expected = (approval.get("evidence") or {}).get("proposal_digest") or (approval.get("scope") or {}).get("proposal_sha256")
        if expected and expected == proposal_digest:
            valid_approval = True
            break
    if not valid_approval:
        errors.append(f"Governance-tier contract violation in {rec['path']}: no exact valid human approval of the current proposal")
        continue

    if requested not in TIER_ORDER:
        errors.append(f"Governance-tier contract violation in {rec['path']}: governance_tier.requested is missing or invalid")
        continue
    if not policy_digest:
        errors.append(f"Governance-tier contract violation in {rec['path']}: proposal was never prepared (governance_tier.policy_digest missing)")
        continue

    archived_policy = verify_policy_archive(layout, policy_digest)
    if archived_policy is None:
        errors.append(
            f"Governance-tier contract violation in {rec['path']}: archived policy {policy_digest} is missing or "
            f"its content digest no longer matches"
        )
        continue

    try:
        entries = validate_declared_scope(proposal_data.get("declared_scope"))
        classification = classify_entries(entries, archived_policy, layout)
        if classification.get("blocker"):
            raise GovernanceTierError(classification["blocker"])
    except GovernanceTierError as exc:
        errors.append(f"Governance-tier contract violation in {rec['path']}: declared scope is missing, malformed, or unclassifiable ({exc})")
        continue

    minimum = classification["classification"]
    if TIER_ORDER[requested] < TIER_ORDER[minimum]:
        errors.append(
            f"Governance-tier contract violation in {rec['path']}: requested_tier {requested} is below the "
            f"archived-policy-recomputed floor {minimum}"
        )

def _controlled_v3_clarification_validation():
    evidence_value = (layout.manifest.get("paths") or {}).get("evidence", "specforge/evidence")
    evidence = (layout.root / evidence_value).resolve()
    presentations = evidence / "presentations"
    clarifications = evidence / "clarifications"
    if not presentations.is_dir():
        return
    for rid, rec in records.items():
        if rec["kind"] != "change":
            continue
        change = rec["data"]
        if (change.get("governance") or {}).get("lifecycle_enforcement") != "controlled_v3":
            continue
        if not (change.get("clarification") or {}).get("required"):
            continue
        proposal_id = (change.get("proposal") or {}).get("current")
        matching_presentations = []
        for path in presentations.glob("PRES-*.yaml"):
            try:
                data = load_yaml(path)
            except Exception:
                continue
            if data.get("proposal") == proposal_id and data.get("change") == rid:
                matching_presentations.append(data)
        if not matching_presentations:
            continue
        presented = sorted(matching_presentations, key=lambda item: item.get("presented_at") or "")[-1]
        session = presented.get("session")
        resolved = []
        if clarifications.is_dir():
            for path in clarifications.glob("CLR-*.yaml"):
                try:
                    item = load_yaml(path)
                except Exception:
                    continue
                if item.get("session") == session and item.get("requested_at") and item.get("resolved_at"):
                    resolved.append(item)
        if not resolved:
            errors.append(f"controlled_v3 clarification required but no resolved clarification evidence exists for {rid}")
            continue
        try:
            presented_at = dt.datetime.fromisoformat(str(presented.get("presented_at")).replace("Z", "+00:00"))
            if not any(dt.datetime.fromisoformat(str(item.get("resolved_at")).replace("Z", "+00:00")) <= presented_at for item in resolved):
                errors.append(f"controlled_v3 clarification was not resolved before proposal presentation for {rid}")
        except Exception:
            errors.append(f"controlled_v3 clarification chronology invalid for {rid}")


_controlled_v3_clarification_validation()
def _managed_completion_guard_validation():
    evidence_value = (layout.manifest.get("paths") or {}).get("evidence", "specforge/evidence")
    evidence = (layout.root / evidence_value).resolve()
    sessions_root = evidence / "managed-sessions"
    completions_root = evidence / "completions"
    metrics_file = evidence / "interaction-metrics.jsonl"
    if not sessions_root.is_dir():
        return
    marks_by_session = {}
    if metrics_file.is_file():
        for raw in metrics_file.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                mark = json.loads(raw)
            except Exception:
                continue
            if isinstance(mark, dict) and mark.get("session"):
                marks_by_session.setdefault(str(mark["session"]), []).append(mark)
    receipts = {}
    if completions_root.is_dir():
        for path in completions_root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"Managed completion guard violation: cannot parse {relative(layout, path)} ({exc})")
                continue
            if isinstance(data, dict) and data.get("session"):
                receipts[str(data["session"])] = (data, path)

    completion_phases = {"implementation_completed", "product_validation_completed", "managed_finish_started", "managed_finish_completed"}
    for session_file in sorted(sessions_root.glob("*.json")):
        try:
            guard = json.loads(session_file.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Managed completion guard violation: cannot parse {relative(layout, session_file)} ({exc})")
            continue
        version = guard.get("completion_guard_version") if isinstance(guard, dict) else None
        if version not in (1, 2, 3):
            continue
        session = str(guard.get("session") or "")
        if not session:
            errors.append(f"Managed completion guard violation: {relative(layout, session_file)} has no session id")
            continue
        marks = marks_by_session.get(session, [])
        if not any(mark.get("phase") in completion_phases for mark in marks):
            continue
        receipt_entry = receipts.get(session)
        linked_changes = sorted({str(mark.get("change")) for mark in marks if mark.get("change")})
        if not receipt_entry:
            if not linked_changes:
                errors.append(f"Managed completion guard violation for {session}: material completion evidence exists without a governed change or completion receipt")
                continue
            linked_records = [records.get(change_id) for change_id in linked_changes]
            if any(rec and rec["kind"] == "change" and rec["data"].get("status") == "completed" for rec in linked_records):
                errors.append(f"Managed completion guard violation for {session}: completed governed work has no final delivery receipt or non-delivery closure")
            continue
        receipt, receipt_path = receipt_entry
        expected_receipt_version = version
        if receipt.get("receipt_version") != expected_receipt_version or receipt.get("type") != "managed_completion_receipt":
            errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: receipt identity invalid")
            continue
        outcome = receipt.get("outcome")
        if outcome == "non_delivery":
            if not str(receipt.get("reason") or "").strip():
                errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: non-delivery reason missing")
            continue
        if outcome != "delivered":
            errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: unsupported outcome {outcome!r}")
            continue
        change_id = str(receipt.get("change") or "")
        change_rec = records.get(change_id)
        if not change_rec or change_rec["kind"] != "change" or change_rec["data"].get("status") != "completed":
            errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: delivered change is not completed")
            continue
        change = change_rec["data"]
        checkpoint_meta = change.get("checkpoint") or {}
        if receipt.get("checkpoint") != checkpoint_meta.get("completed_in") or receipt.get("acceptance") != checkpoint_meta.get("acceptance"):
            errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: checkpoint authority binding mismatch")
        deliverables = receipt.get("deliverables") or []
        if not deliverables:
            errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: delivered artifact list is empty")
        for item in deliverables:
            if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
                errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: malformed delivered artifact")
            elif item.get("classification") != "material":
                errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: artifact was not recorded as project material")
        if version in (2, 3):
            request_digest = ((guard.get("request") or {}).get("digest"))
            project = receipt.get("project_definition") or {}
            finish = project.get("finish") or {}
            current_work = finish.get("current_work") or {}
            if not request_digest or project.get("request_digest") != request_digest:
                errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: request digest binding missing")
            if current_work.get("request_digest") != request_digest or current_work.get("change") != change_id:
                errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: PROJECT.md current-work binding is stale")
            action = project.get("action")
            if action == "updated":
                reconciliation = guard.get("project_definition_reconciliation") or {}
                expected = reconciliation.get("prepared_sha256")
                if not expected or finish.get("sha256") != expected:
                    errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: PROJECT.md prepared hash mismatch")
                proposal_id = (change.get("proposal") or {}).get("current")
                proposal_rec = records.get(str(proposal_id))
                binding = (proposal_rec["data"].get("project_definition_reconciliation") or {}) if proposal_rec else {}
                if binding.get("sha256") != expected or binding.get("request_digest") != request_digest or binding.get("change") != change_id:
                    errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: PROJECT.md was not bound by approved proposal")
            elif action == "unchanged":
                start = project.get("start") or {}
                start_work = start.get("current_work") or {}
                if start.get("sha256") != finish.get("sha256") or start_work.get("request_digest") != request_digest or start_work.get("change") != change_id:
                    errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: stale PROJECT.md declared unchanged")
            else:
                errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: project-definition action invalid")

            if version == 3:
                managed = finish.get("managed_definition") or {}
                if managed.get("definition_format_version") != 2:
                    errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: PROJECT.md managed definition v2 missing")
                if (
                    managed.get("request_digest") != request_digest
                    or managed.get("change") != change_id
                    or managed.get("status") != "current"
                ):
                    errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: PROJECT.md managed definition stale")
                reconciliation = guard.get("project_definition_reconciliation") or {}
                proposal_id = (change.get("proposal") or {}).get("current")
                proposal_rec = records.get(str(proposal_id))
                binding = (proposal_rec["data"].get("project_definition_reconciliation") or {}) if proposal_rec else {}
                if (
                    reconciliation.get("definition_format_version") != 2
                    or binding.get("definition_format_version") != 2
                ):
                    errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: PROJECT.md definition format not approval-bound")
                prepared_rel = reconciliation.get("prepared_path")
                prepared_sha = reconciliation.get("prepared_sha256")
                if prepared_rel and prepared_sha:
                    prepared_path = (layout.root / str(prepared_rel)).resolve()
                    if not prepared_path.is_file() or hashlib.sha256(prepared_path.read_bytes()).hexdigest() != prepared_sha:
                        errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: prepared PROJECT.md evidence missing or changed")
                else:
                    errors.append(f"Managed completion guard violation in {relative(layout, receipt_path)}: prepared PROJECT.md evidence binding missing")


_managed_completion_guard_validation()


if errors:
    emit_progress("failed", None, None, "full repository integrity validation failed")
    print("SpecForge validation FAILED")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

authorization_tool = layout.tool_root / "specforge-authorization.py"
if authorization_tool.is_file():
    authorization = subprocess.run(
        [sys.executable, str(authorization_tool), "--root", str(ROOT), "--json"],
        capture_output=True,
        text=True,
    )
    if authorization.returncode:
        print("SpecForge validation FAILED")
        print(" - Implementation authorization integrity check failed")
        if authorization.stdout.strip():
            print(authorization.stdout.strip())
        if authorization.stderr.strip():
            print(authorization.stderr.strip())
        sys.exit(1)
elif layout.mode == "project_format_1":
    print("SpecForge validation FAILED")
    print(" - Implementation authorization tool missing")
    sys.exit(1)

emit_progress("complete", len(records), len(records), "full repository integrity validation complete")
print("SpecForge validation PASSED")
print(f" Repository: {ROOT}")
print(f" Project format mode: {layout.mode}")
print(f" Validation mode: {VALIDATION_MODE}")
if SCOPED_CHANGE_IDS is not None:
    print(" Scoped changes: " + ", ".join(sorted(SCOPED_CHANGE_IDS)))
print(f" Canonical records discovered: {len(records)}")
print(" Nested SpecForge projects: excluded from parent validation")