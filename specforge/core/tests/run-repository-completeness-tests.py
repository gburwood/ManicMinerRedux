#!/usr/bin/env python3
from pathlib import Path
import re, sys

CORE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE_ROOT / "tools"))
from specforge_project import discover_layout, project_root

ROOT = project_root(Path(__file__).resolve())
layout = discover_layout(ROOT)
manifest = layout.manifest
spec = manifest.get("specification") or {}

product_rel = spec.get("product_specification")
model_rel = spec.get("canonical_data_model")
assert product_rel, "Manifest does not declare product_specification"
assert model_rel, "Manifest does not declare canonical_data_model"

product = (ROOT / product_rel).resolve()
model = (ROOT / model_rel).resolve()
assert product.is_file(), f"Missing authoritative product specification: {product_rel}"
assert model.is_file(), f"Missing authoritative canonical data model: {model_rel}"

bad_patterns = [
    r"intentionally concise",
    r"full reviewed product specification as it evolves",
    r"candidate reconstruction",
    r"not authoritative until",
    r"\bplaceholder\b",
]

# Current authorities may be deliberate normative deltas over repository-contained
# predecessor documents. Repository completeness therefore applies to the complete
# normative chain, not to an arbitrary minimum byte count for the newest delta file.
# A predecessor is followed only when the current document explicitly says it
# "succeeds" that repository-local markdown document.
SUCCEEDS_RE = re.compile(r"\bsucceeds\s+`([^`]+\.md)`", re.I)


def normative_chain(start: Path):
    chain = []
    seen = set()
    current = start.resolve()
    while True:
        assert current not in seen, f"Normative specification cycle detected at {current}"
        seen.add(current)
        assert current.is_file(), f"Missing normative specification document: {current}"
        chain.append(current)
        text = current.read_text(encoding="utf-8")
        match = SUCCEEDS_RE.search(text)
        if not match:
            break
        predecessor = (current.parent / match.group(1)).resolve()
        assert predecessor.parent == current.parent, (
            f"Normative predecessor must remain repository-local beside current authority: {match.group(1)}"
        )
        current = predecessor
    return chain


def assert_complete_chain(start: Path, label: str):
    chain = normative_chain(start)
    for path in chain:
        text = path.read_text(encoding="utf-8")
        assert text.strip(), f"{label} normative document {path.name} is empty"
        for pattern in bad_patterns:
            assert not re.search(pattern, text, re.I), (
                f"{label} normative document {path.name} declares incomplete/non-authoritative content: {pattern}"
            )
    return chain


product_chain = assert_complete_chain(product, product_rel)
model_chain = assert_complete_chain(model, model_rel)

# The current authorities must themselves be first in their normative chains.
assert product_chain[0] == product
assert model_chain[0] == model

print("Repository completeness tests PASSED")
