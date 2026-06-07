from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from api.adapters.audit_log import verify_audit_chain, write_audit_event
from api.database import Base, AuditEvent
from api.domain.audit_log import ZERO_EVENT_HASH


PHASE13_TABLES = {
    "methodology_version_set",
    "scan_runs",
    "scan_progress",
    "execution_samples",
    "scan_steps",
    "idempotency_keys",
    "cost_ledger",
    "scan_raw_response_archive",
    "scan_provenance",
    "samples",
    "classification",
    "domain_classification",
    "avs_computation",
    "audit_event",
}


def _sessionmaker():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def test_phase13_foundation_schema_tables_and_constraints_exist():
    engine, _ = _sessionmaker()
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            assert PHASE13_TABLES.issubset(table_names)

            client_columns = {column["name"] for column in inspector.get_columns("clients")}
            assert {
                "tier",
                "cost_budget_default_usd",
                "byok",
                "byok_keys",
                "owned_domains",
                "competitor_domains",
            }.issubset(client_columns)

            version_columns = {
                column["name"]
                for column in inspector.get_columns("methodology_version_set")
            }
            assert {
                "avs_formula_version",
                "bank_version",
                "stance_classifier_version",
                "source_classifier_version",
                "sampling_config_version",
                "provider_model_snapshot_version",
                "valid_from",
                "valid_to",
                "sys_period",
                "spec_document_hash",
            }.issubset(version_columns)

            audit_indexes = {
                index["name"] for index in inspector.get_indexes("audit_event")
            }
            assert {
                "idx_audit_event_resource",
                "idx_audit_event_actor",
                "idx_audit_event_correlation",
            }.issubset(audit_indexes)

            scan_run_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("scan_runs")
            }
            assert "uq_scan_runs_client_idempotency" in scan_run_constraints
            scan_run_columns = {
                column["name"] for column in inspector.get_columns("scan_runs")
            }
            assert "providers" in scan_run_columns

            sample_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("samples")
            }
            assert "uq_sample_scan_question_provider_index" in sample_constraints
            execution_sample_columns = {
                column["name"]: column for column in inspector.get_columns("execution_samples")
            }
            assert {
                "planned_provider_model",
                "provider_model",
                "temperature",
                "top_p",
                "sample_plan_hash",
                "request_payload_hash",
                "raw_response_text",
                "raw_response_pointer",
                "raw_response_hash",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "response_received_at",
                "latency_ms",
                "methodology_version",
                "cache_bust",
            }.issubset(execution_sample_columns)
            assert execution_sample_columns["provider_model"]["nullable"] is True
            assert execution_sample_columns["seed"]["nullable"] is True

            canonical_sample_columns = {
                column["name"]: column for column in inspector.get_columns("samples")
            }
            assert {
                "top_p",
                "raw_response_pointer",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "methodology_version",
            }.issubset(canonical_sample_columns)
            assert canonical_sample_columns["seed"]["nullable"] is True

            avs_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("avs_computation")
            }
            assert "uq_avs_computation_scan_methodology" in avs_constraints

            # The (sample_id, classifier_type, classifier_version) uniqueness is
            # enforced by a unique index named ``uq_classification_sample_type_version``
            # (migration 0017 created it via CREATE UNIQUE INDEX, and the model
            # declares a matching unique Index), not a table-level unique constraint.
            classification_unique_indexes = {
                index["name"]
                for index in inspector.get_indexes("classification")
                if index.get("unique")
            }
            assert "uq_classification_sample_type_version" in classification_unique_indexes

            domain_cache_columns = {
                column["name"] for column in inspector.get_columns("domain_classification")
            }
            assert {
                "domain",
                "source_class",
                "classifier_version",
                "classifier_model",
                "prompt_hash",
                "confidence",
                "source",
                "evidence",
                "expires_at",
            }.issubset(domain_cache_columns)

            raw_archive_columns = {
                column["name"] for column in inspector.get_columns("scan_raw_response_archive")
            }
            assert {
                "scan_id",
                "archive_type",
                "sample_count",
                "archive_url",
                "archive_hash",
            }.issubset(raw_archive_columns)
    finally:
        engine.dispose()


def test_audit_events_are_hash_chained_and_tamper_detectable():
    engine, Session = _sessionmaker()
    session = Session()
    key = b"test audit key"
    try:
        first = write_audit_event(
            session,
            actor_type="system",
            actor_id="phase13-test",
            action="methodology.version.approved",
            resource_type="methodology_version_set",
            resource_id="mvs-1",
            after_state={"label": "v1"},
            reason="acceptance test",
            hmac_key=key,
            hmac_key_version=1,
        )
        second = write_audit_event(
            session,
            actor_type="system",
            actor_id="phase13-test",
            action="scan.started",
            resource_type="scan_run",
            resource_id="scan-1",
            after_state={"status": "running"},
            hmac_key=key,
            hmac_key_version=1,
        )
        session.commit()

        assert first.prev_event_hash == ZERO_EVENT_HASH
        assert second.prev_event_hash == first.event_hash
        assert len(first.event_hash) == 32
        assert verify_audit_chain(session, hmac_keys={1: key}) == []

        session.query(AuditEvent).filter(AuditEvent.id == second.id).update(
            {"after_state": {"status": "tampered"}}
        )
        session.commit()

        violations = verify_audit_chain(session, hmac_keys={1: key})
        assert [(violation.event_id, violation.reason) for violation in violations] == [
            (second.id, "event hash mismatch")
        ]
    finally:
        session.close()
        engine.dispose()
