from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from api.adapters.audit_log import verify_audit_chain, write_audit_event
from api.database import Base, AuditEvent
from api.domain.audit_log import ZERO_EVENT_HASH


PHASE13_TABLES = {
    "methodology_version_set",
    "scan_runs",
    "scan_progress",
    "samples",
    "scan_steps",
    "idempotency_keys",
    "cost_ledger",
    "scan_provenance",
    "sample",
    "classification",
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

            sample_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("sample")
            }
            assert "uq_sample_scan_question_provider_index" in sample_constraints

            avs_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("avs_computation")
            }
            assert "uq_avs_computation_scan_methodology" in avs_constraints
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
