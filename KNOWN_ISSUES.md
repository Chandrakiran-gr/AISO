# Known Issues

## Deferred: source evidence artifact expectation mismatch

- **File path:** `tests/test_database_schema.py`
- **Symptom:** `DatabaseSchemaTests.test_scan_metrics_persistence_registers_source_evidence_artifact` expects a `source_evidence_jsonl` `ScanArtifact`, but `full_stack/scan_metrics.py` currently documents and implements JSON/JSONL source evidence as internal-only analysis input rather than a downloadable artifact record.
- **Status:** Deferred. This is unrelated to Phase 12.1 onboarding intake and should be reconciled in a focused source-evidence/artifact policy cleanup.

## Deferred: CAI-1.0 methodology specification

- **Spec gap:** `methodology/AVS-1.0.md` defines the high-level CAI formula but does not define the Coverage, Authority, or Recency sub-index formulas or aggregation rules.
- **Pipeline placeholder:** A clearly marked placeholder exists in `api/adapters/scan_execution.py` between `compute_scan_avs` and `publish_scan`, where a future `compute_cai` saga step will belong.
- **Status:** Deferred. Draft `methodology/CAI-1.0.md` or an AVS methodology revision before creating a CAI table, writing CAI calculation code, or displaying a numeric CAI value.
