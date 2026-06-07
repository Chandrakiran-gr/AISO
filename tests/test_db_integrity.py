"""Verify the Phase 1 delete policy actually behaves correctly under SQLite FK
enforcement: client-owned rows CASCADE, optional links SET NULL, and the
immutable records (scan_provenance / methodology_version_set references) are
protected (no ON DELETE action).

The application engine enables ``PRAGMA foreign_keys=ON`` in api.database; here we
enable it explicitly on a throwaway engine so the cascade rules are exercised.
"""

import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from api.database import (
    Base,
    Client,
    Scan,
    ScanCitation,
    ScanResult,
    SourceProfile,
    User,
)


def _fk_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path/'it.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    return engine


def _uid() -> str:
    return uuid.uuid4().hex


def test_deleting_client_cascades_to_owned_rows():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _fk_engine(Path(tmp))
        Session = sessionmaker(bind=engine)
        s = Session()
        u = User(id=_uid(), email=f"{_uid()}@x.com")
        c = Client(id=_uid(), user_id=u.id, name="Acme", url="https://acme.test")
        sc = Scan(id=_uid(), client_id=c.id)
        sr = ScanResult(id=_uid(), scan_id=sc.id, client_id=c.id, provider="openai", group="G1")
        # Insert parent-before-child explicitly: with FK enforcement on and no
        # relationship() metadata, the UOW does not infer insert ordering.
        for obj in (u, c, sc, sr):
            s.add(obj)
            s.flush()
        s.commit()

        s.delete(c)
        s.commit()
        assert s.query(Scan).count() == 0
        assert s.query(ScanResult).count() == 0
        # the user is NOT owned by the client, so it remains
        assert s.query(User).count() == 1
        s.close()
        engine.dispose()


def test_deleting_source_profile_sets_citation_link_null():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _fk_engine(Path(tmp))
        Session = sessionmaker(bind=engine)
        s = Session()
        u = User(id=_uid(), email=f"{_uid()}@x.com")
        c = Client(id=_uid(), user_id=u.id, name="Acme", url="https://acme.test")
        sc = Scan(id=_uid(), client_id=c.id)
        sp = SourceProfile(id=_uid(), client_id=c.id, canonical_url="https://src.test/a")
        cite = ScanCitation(
            id=_uid(), client_id=c.id, scan_id=sc.id, provider="openai",
            citation_url="https://src.test/a", source_profile_id=sp.id,
        )
        for obj in (u, c, sc, sp, cite):
            s.add(obj)
            s.flush()
        s.commit()

        s.delete(sp)
        s.commit()
        s.expire_all()
        surviving = s.query(ScanCitation).one()
        assert surviving.source_profile_id is None  # link nulled, row kept
        s.close()
        engine.dispose()


def test_protected_foreign_keys_have_no_ondelete_action():
    """scan_provenance's FKs and every methodology_version_set reference must be
    NO ACTION so immutable records can't be deleted out from under them."""
    with tempfile.TemporaryDirectory() as tmp:
        engine = _fk_engine(Path(tmp))
        insp = inspect(engine)

        def ondelete_actions(table: str) -> dict[str, str | None]:
            return {
                tuple(fk["constrained_columns"])[0]: fk.get("options", {}).get("ondelete")
                for fk in insp.get_foreign_keys(table)
            }

        prov = ondelete_actions("scan_provenance")
        assert prov.get("client_id") in (None, "NO ACTION")
        assert prov.get("scan_id") in (None, "NO ACTION")
        assert prov.get("methodology_version_set_id") in (None, "NO ACTION")

        # methodology_version_set_id references everywhere stay protected
        for table in ("scan_runs", "scan_metrics", "scan_source_citations", "avs_computation"):
            actions = ondelete_actions(table)
            if "methodology_version_set_id" in actions:
                assert actions["methodology_version_set_id"] in (None, "NO ACTION")

        engine.dispose()
