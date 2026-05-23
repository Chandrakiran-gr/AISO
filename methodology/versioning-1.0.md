# AISO Methodology Versioning and Audit Log — Specification v1.0.0

**Status:** Active
**Effective from:** 2026-06-01

## Architecture

**Hybrid CRUD-with-append-only-domain-event-log.** Not pure event sourcing.

| Data class | Mutation | Pattern |
|---|---|---|
| Raw provider responses | Insert-only | Event-sourced (immutable facts) |
| Per-sample classifications | Insert-only; re-run produces new rows under new classifier version | Event-sourced |
| Methodology version records | Insert-only | Event-sourced (versioned spec) |
| Scan provenance bundle | Insert-only, signed at scan close | Event-sourced + hash chain |
| Computed AVS scores | Insert-only per (scan_id, methodology_version_set_id) | Event-sourced projection |
| Clients, users, billing | CRUD | CRUD + temporal_tables |
| In-flight scan state | CRUD with state machine | CRUD + audit log triggers |
| Configuration (weights, thresholds) | Should never change in place | Versioned spec table |

## Six-component methodology version set

Every scan stamps one `methodology_version_set_id`. The set composes six independently versioned components:

| Component | SemVer field | Bump rule |
|---|---|---|
| `avs_formula_version` | 1.x.y.z | Per `AVS-1.0.md` rules |
| `bank_version` | 1.x.y.z | Per `question-bank-1.0.md` rules |
| `stance_classifier_version` | 1.x.y.z | Per `classifier-1.0.md` rules |
| `source_classifier_version` | 1.x.y.z | Per `classifier-1.0.md` rules |
| `sampling_config_version` | 1.x.y.z | Per `N-sampling-1.0.md` rules |
| `provider_model_snapshot` | provider-supplied | Per-sample, not under AISO control |

The set itself receives a monotonic ID and a date-anchored label (e.g. `AISO-2026.06`).

## Bitemporal modeling

Every methodology version set carries:
- **Valid time**: `valid_from`, `valid_to` (real-world canonical period)
- **Transaction time**: `sys_period` (when AISO recorded the fact)

Reference: Snodgrass (1999); SQL:2011 system-versioned tables.

## Postgres DDL (canonical)

```sql
CREATE TABLE methodology_version_set (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  label                       TEXT NOT NULL UNIQUE,
  avs_formula_version         TEXT NOT NULL,
  bank_version                TEXT NOT NULL,
  stance_classifier_version   TEXT NOT NULL,
  source_classifier_version   TEXT NOT NULL,
  sampling_config_version     TEXT NOT NULL,
  valid_from                  TIMESTAMPTZ NOT NULL,
  valid_to                    TIMESTAMPTZ,
  sys_period                  TSTZRANGE NOT NULL DEFAULT tstzrange(now(), NULL),
  spec_document_url           TEXT NOT NULL,
  spec_document_hash          BYTEA NOT NULL,
  change_memo_url             TEXT,
  approved_by                 TEXT NOT NULL,
  approved_at                 TIMESTAMPTZ NOT NULL,
  shadow_run_started_at       TIMESTAMPTZ,
  shadow_run_ended_at         TIMESTAMPTZ,
  superseded_by               UUID REFERENCES methodology_version_set(id)
);

CREATE TABLE scan_provenance (
  scan_id                     UUID PRIMARY KEY,
  client_id                   UUID NOT NULL,
  methodology_version_set_id  UUID NOT NULL REFERENCES methodology_version_set(id),
  scan_started_at             TIMESTAMPTZ NOT NULL,
  scan_completed_at           TIMESTAMPTZ NOT NULL,
  question_count              INT NOT NULL,
  sample_count                INT NOT NULL,
  raw_response_archive_url    TEXT NOT NULL,
  raw_response_archive_hash   BYTEA NOT NULL,
  scan_manifest_hash          BYTEA NOT NULL,
  git_sha                     TEXT NOT NULL,
  computed_by_host            TEXT NOT NULL,
  prev_provenance_hash        BYTEA,
  this_provenance_hash        BYTEA NOT NULL,
  signed_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE ON scan_provenance FROM PUBLIC, aiso_app;
GRANT INSERT, SELECT ON scan_provenance TO aiso_app;

CREATE TABLE sample (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id                     UUID NOT NULL REFERENCES scan_provenance(scan_id),
  question_id                 UUID NOT NULL,
  provider                    TEXT NOT NULL,
  provider_model              TEXT NOT NULL,
  system_fingerprint          TEXT,
  temperature                 NUMERIC(4,3) NOT NULL,
  seed                        BIGINT NOT NULL,
  sample_index                INT NOT NULL,
  request_payload_hash        BYTEA NOT NULL,
  raw_response_text           TEXT NOT NULL,
  raw_response_hash           BYTEA NOT NULL,
  response_received_at        TIMESTAMPTZ NOT NULL,
  latency_ms                  INT,
  UNIQUE (scan_id, question_id, provider, sample_index)
);
REVOKE UPDATE, DELETE ON sample FROM PUBLIC, aiso_app;

CREATE TABLE classification (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sample_id                   UUID NOT NULL REFERENCES sample(id),
  classifier_type             TEXT NOT NULL,
  classifier_version          TEXT NOT NULL,
  classifier_model            TEXT NOT NULL,
  prompt_hash                 BYTEA NOT NULL,
  self_consistency_n          INT,
  individual_judgments        JSONB,
  consensus_value             TEXT NOT NULL,
  consensus_confidence        NUMERIC(5,4),
  judged_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE ON classification FROM PUBLIC, aiso_app;

CREATE TABLE avs_computation (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id                     UUID NOT NULL REFERENCES scan_provenance(scan_id),
  methodology_version_set_id  UUID NOT NULL REFERENCES methodology_version_set(id),
  avs_value                   NUMERIC(6,3) NOT NULL,
  presence                    NUMERIC(6,5) NOT NULL,
  prominence                  NUMERIC(6,5) NOT NULL,
  positivity                  NUMERIC(6,5) NOT NULL,
  ci_lower_95                 NUMERIC(6,3) NOT NULL,
  ci_upper_95                 NUMERIC(6,3) NOT NULL,
  ci_method                   TEXT NOT NULL,
  bootstrap_iterations        INT,
  computed_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  computed_by_git_sha         TEXT NOT NULL,
  is_primary                  BOOLEAN NOT NULL DEFAULT true,
  UNIQUE (scan_id, methodology_version_set_id)
);
REVOKE UPDATE, DELETE ON avs_computation FROM PUBLIC, aiso_app;
GRANT INSERT, SELECT, UPDATE(is_primary) ON avs_computation TO aiso_app;

CREATE TABLE audit_event (
  id                          BIGSERIAL PRIMARY KEY,
  event_time                  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  actor_type                  TEXT NOT NULL,
  actor_id                    TEXT NOT NULL,
  actor_session_id            TEXT,
  source_ip                   INET,
  user_agent                  TEXT,
  action                      TEXT NOT NULL,
  resource_type               TEXT NOT NULL,
  resource_id                 TEXT NOT NULL,
  before_state                JSONB,
  after_state                 JSONB,
  reason                      TEXT,
  correlation_id              UUID,
  txid                        BIGINT NOT NULL DEFAULT txid_current(),
  prev_event_hash             BYTEA,
  event_hash                  BYTEA NOT NULL,
  hmac_key_version            INT NOT NULL
) PARTITION BY RANGE (event_time);

CREATE INDEX idx_audit_event_resource    ON audit_event (resource_type, resource_id);
CREATE INDEX idx_audit_event_actor       ON audit_event (actor_type, actor_id);
CREATE INDEX idx_audit_event_correlation ON audit_event (correlation_id);
REVOKE UPDATE, DELETE ON audit_event FROM PUBLIC, aiso_app;
GRANT INSERT, SELECT ON audit_event TO aiso_app;
```

## Postgres roles (required)

```sql
CREATE ROLE aiso_app        LOGIN PASSWORD '...';
CREATE ROLE aiso_compliance LOGIN PASSWORD '...';
CREATE ROLE aiso_migration  LOGIN PASSWORD '...';

GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO aiso_app;
GRANT UPDATE ON clients, users, scan_in_flight TO aiso_app;
GRANT UPDATE (is_primary) ON avs_computation   TO aiso_app;
GRANT SELECT ON audit_event, scan_provenance, sample, classification TO aiso_compliance;
```

## Hash chain for audit log

```python
def write_audit_event(event_data: dict, hmac_key: bytes, key_version: int):
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(42)")
        prev = db.fetch_one("SELECT event_hash FROM audit_event ORDER BY id DESC LIMIT 1")
        prev_hash = prev["event_hash"] if prev else b"\x00" * 32

        canonical = canonical_serialize(event_data)  # RFC 8785 JCS or sorted-keys JSON
        message   = prev_hash + canonical
        event_hash = hmac.new(hmac_key, message, hashlib.sha256).digest()

        db.execute("INSERT INTO audit_event (...) VALUES (...)",
                   ..., prev_hash, event_hash, key_version)
```

Verification: nightly cron walks chain, recomputes every link, alerts on break.

## Events to capture

```
AUTHENTICATION:    auth.login.success / failure, auth.logout, auth.mfa.*, auth.session.expired
RBAC:              rbac.role.* , rbac.user.role_*, rbac.api_key.*
DATA ACCESS:       data.client_scan.read, data.raw_response.read, data.export.created
SCAN OPERATIONS:   scan.scheduled / started / completed / failed / cancelled
METHODOLOGY:       methodology.version.proposed / approved / activated / superseded
                   bank.question.* , classifier.gold_set.updated, classifier.threshold.changed
OVERRIDES:         classification.manual_override, avs.recomputed, avs.promoted_primary, client.data.deleted
ADMINISTRATIVE:    admin.config.changed, admin.feature_flag.toggled, admin.break_glass.used
FAILED OPS:        scan.provider.timeout, scan.classifier.gate_failure, scan.budget.exceeded
```

## Storage tiering

| Tier | Storage | Retention | Mutability |
|---|---|---|---|
| Hot | Postgres `audit_event`, partitioned monthly | 90 days | Insert-only (REVOKE U/D) |
| Warm | Detached partitions, separate tablespace | 90d – 3y | Insert-only |
| Cold | S3 Object Lock (compliance mode) | 3y – 7y | Immutable (WORM) |
| Frozen | S3 Glacier Deep Archive | 7y+ | Immutable |

## Re-aggregation pipeline

Given any (scan_id, target_methodology_version_set_id):
1. Verify raw response archive SHA-256 matches `scan_provenance.raw_response_archive_hash`.
2. Load samples from `sample` table.
3. Re-classify under target classifier versions IF newer.
4. Apply AVS formula at target version.
5. Persist as new immutable `avs_computation` row with `is_primary=false`.
6. Promotion to `is_primary=true` is itself an audit event (`avs.promote_primary`).

## SOC 2 mapping

| Criterion | What auditors check | AISO control |
|---|---|---|
| CC6 — Logical & physical access | RBAC, SSO, access events | Audit log of `auth.*` + `rbac.*` |
| CC7 — System operations | Monitoring, detection, incident response | Audit log of `scan.*`, `data.*` + alerting |
| CC8 — Change management | Tested, approved changes | ADR log + `methodology.version.*` events |
| CC4 — Monitoring | Ongoing control evaluation | Quarterly access review documented |

## Retention (cross-framework)

| Framework | Required |
|---|---|
| SOC 2 | No specific period; de facto ≥12 months |
| PCI DSS v4.0 | 12 months, 3 months immediately available |
| HIPAA | 6 years (§164.316) |
| SOX | 7 years |
| ISO 27001 | ≥12 months recommended |

**AISO target:** 3-year hot/warm in Postgres + S3 Object Lock; 7-year cold in Glacier Deep Archive.

## Version bump runbook

| Stage | Activity | Gate |
|---|---|---|
| 0. Proposal | Founder drafts ADR (Nygard format) | Self-review |
| 1. Sensitivity analysis | Compute proposed methodology on last 90 days | Quantitative impact memo |
| 2. Shadow run | New methodology in parallel; both AVS values stored | 30–90 days (12 months for major) |
| 3. Customer preview | Affected enterprises see proposed change | 14 days |
| 4. Change memo | Public memo published; email all customers | Memo ≥14 days before activation |
| 5. Activation | New `is_primary`; old remains queryable forever | Audit event `methodology.version.activated` |

## Limitations

1. Pure event sourcing not appropriate at AISO's scale; hybrid is the engineering call.
2. Hash chains are detection, not prevention; WORM exports + offline anchoring required for state-actor threat models.
3. Bitemporal in Postgres is verbose; `temporal_tables` C extension not supported on managed Postgres (use PL/pgSQL rewrite).
4. AWS QLDB end-of-support 2025-07-31; use Postgres + S3 Object Lock.

## References

- Snodgrass (1999) — Developing Time-Oriented Database Applications in SQL
- Fowler — Bitemporal History (martinfowler.com/articles/bitemporal-history.html)
- Stripe — APIs as infrastructure (Brandur Leach, 2017)
- 21 CFR Part 11.10(e) — audit trail requirement
- ICH E6(R3) — audit trail definition (2025)
- ALCOA++ (EMA 2023) — data integrity principles
- W3C PROV-O — provenance ontology
- AICPA TSC — SOC 2 Trust Services Criteria
