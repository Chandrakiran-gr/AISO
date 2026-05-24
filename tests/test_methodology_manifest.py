import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MANIFEST.txt"

EXPECTED_SPEC_PATHS = [
    "methodology/AVS-1.0.md",
    "methodology/N-sampling-1.0.md",
    "methodology/classifier-1.0.md",
    "methodology/question-bank-1.0.md",
    "methodology/pricing-1.0.md",
    "methodology/execution-1.0.md",
    "methodology/versioning-1.0.md",
    "methodology/pipeline-1.0.md",
]


def _parse_manifest() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative_path = line.split(maxsplit=1)
        entries[relative_path] = digest
    return entries


def test_methodology_manifest_matches_current_spec_hashes():
    entries = _parse_manifest()

    assert list(entries.keys()) == EXPECTED_SPEC_PATHS

    for relative_path, expected_digest in entries.items():
        spec_path = ROOT / relative_path
        actual_digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        assert actual_digest == expected_digest
