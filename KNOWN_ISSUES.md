# Known Issues

## Deferred: source evidence artifact expectation mismatch

- **File path:** `tests/test_database_schema.py`
- **Symptom:** `DatabaseSchemaTests.test_scan_metrics_persistence_registers_source_evidence_artifact` expects a `source_evidence_jsonl` `ScanArtifact`, but `full_stack/scan_metrics.py` currently documents and implements JSON/JSONL source evidence as internal-only analysis input rather than a downloadable artifact record.
- **Status:** Deferred. This is unrelated to Phase 12.1 onboarding intake and should be reconciled in a focused source-evidence/artifact policy cleanup.
