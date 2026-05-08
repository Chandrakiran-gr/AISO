import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.database import Base, Client, Scan, ScanArtifact, User
from api.routes.pipeline import download_scan_artifact


class ArtifactAccessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _seed_artifact(
        self,
        session,
        email: str,
        storage_path: str,
        *,
        storage_backend: str = "local",
    ) -> None:
        session.add(User(id="user-1", email=email, provider="credentials", is_active=True))
        session.add(Client(id="client-1", user_id="user-1", name="AISO Demo", url="https://example.com"))
        session.add(Scan(id="scan-1", client_id="client-1", status="complete"))
        session.add(
            ScanArtifact(
                id="artifact-1",
                client_id="client-1",
                scan_id="scan-1",
                artifact_type="collect_csv",
                file_format="csv",
                storage_backend=storage_backend,
                storage_path=storage_path,
                original_filename="scan-results.csv",
                mime_type="text/csv",
                size_bytes=12,
            )
        )
        session.commit()

    def test_admin_email_can_download_local_artifact_on_free_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / "clients" / "client-1" / "scans" / "scan-1" / "raw" / "scan-results.csv"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("question\none\n", encoding="utf-8")

            session = self.Session()
            try:
                self._seed_artifact(session, "admin@aisoglobal.com", str(artifact_path))
                with patch.dict("os.environ", {"AISO_STORAGE_ROOT": tmp, "AISO_PLAN": "free"}):
                    response = asyncio.run(
                        download_scan_artifact(
                            "client-1",
                            "scan-1",
                            "artifact-1",
                            db=session,
                            user_id="user-1",
                        )
                    )

                self.assertIsInstance(response, FileResponse)
                self.assertEqual(Path(response.path).resolve(), artifact_path.resolve())
            finally:
                session.close()

    def test_admin_email_can_download_onedrive_artifact_on_free_plan(self):
        session = self.Session()
        try:
            self._seed_artifact(
                session,
                "admin@aisoglobal.com",
                "onedrive://drive-1/item-1",
                storage_backend="onedrive",
            )
            with patch.dict("os.environ", {"AISO_PLAN": "free"}), patch(
                "api.routes.pipeline.download_onedrive_artifact",
                return_value=b"question\none\n",
            ):
                response = asyncio.run(
                    download_scan_artifact(
                        "client-1",
                        "scan-1",
                        "artifact-1",
                        db=session,
                        user_id="user-1",
                    )
                )

            self.assertEqual(response.body, b"question\none\n")
            self.assertEqual(response.media_type, "text/csv")
        finally:
            session.close()

    def test_non_entitled_free_user_cannot_download_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / "clients" / "client-1" / "scans" / "scan-1" / "raw" / "scan-results.csv"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("question\none\n", encoding="utf-8")

            session = self.Session()
            try:
                self._seed_artifact(session, "free@example.com", str(artifact_path))
                with patch.dict("os.environ", {"AISO_STORAGE_ROOT": tmp, "AISO_PLAN": "free"}):
                    with self.assertRaises(HTTPException) as ctx:
                        asyncio.run(
                            download_scan_artifact(
                                "client-1",
                                "scan-1",
                                "artifact-1",
                                db=session,
                                user_id="user-1",
                            )
                        )

                self.assertEqual(ctx.exception.status_code, 403)
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
