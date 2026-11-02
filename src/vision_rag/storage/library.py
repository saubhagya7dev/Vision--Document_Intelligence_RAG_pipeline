"""Durable local document workflows with compensating vector/file operations."""

import hashlib
import logging
import os
import shutil
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, BinaryIO, Callable
from uuid import UUID, uuid4

from vision_rag.ingest.document_loader import DocumentLoader
from vision_rag.ingest.pipeline import IngestionCancelled, IngestionPipeline
from vision_rag.storage.metadata import Conflict, Metadata, now
from vision_rag.storage.ownership import LibraryOwnership
from vision_rag.telemetry import stage, trace
from vision_rag.vector_stores.qdrant_store import QdrantVectorStore

logger = logging.getLogger(__name__)


class ResourceLimit(ValueError):
    pass


class WorkerInterrupted(Exception):
    pass


class DocumentLibrary:
    def __init__(
        self,
        root: Path,
        loader: DocumentLoader,
        store: QdrantVectorStore,
        pipeline: Callable[[], IngestionPipeline],
        profile: str,
        workspace: str = "local",
        max_upload_bytes: int = 100 * 1024 * 1024,
        max_pages: int = 1000,
    ) -> None:
        self.root = root.resolve()
        self.owner = LibraryOwnership(self.root)
        try:
            self.metadata = Metadata(self.root / "metadata.sqlite3", workspace)
        except BaseException:
            self.owner.close()
            raise
        self.loader, self.store, self.pipeline = loader, store, pipeline
        self.profile, self.workspace = profile, workspace
        self.max_upload_bytes, self.max_pages = max_upload_bytes, max_pages
        self.access = RLock()
        self.stop_event, self.wake_event = Event(), Event()
        self.thread: Thread | None = None

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("Artifact path escapes library")
        return path

    @staticmethod
    def validate_filename(filename: str) -> None:
        if (
            not filename.lower().endswith(".pdf")
            or len(filename) > 255
            or any(char in filename for char in ("/", "\\", ":"))
            or any(ord(char) < 32 for char in filename)
        ):
            raise ValueError("Provide a PDF filename without path components")

    def upload(
        self,
        stream: BinaryIO,
        filename: str,
        replace_document: str | None = None,
        legacy_path: str | None = None,
    ) -> dict[str, Any]:
        self.validate_filename(filename)
        version_id = str(uuid4())
        temporary = self.path(f"incoming/{version_id}.part")
        key = f"originals/{version_id}.pdf"
        target = self.path(key)
        temporary.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        try:
            with stage("upload_handling"), temporary.open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_upload_bytes:
                        raise ResourceLimit("Upload exceeds configured size limit")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            with temporary.open("rb") as source:
                if not source.read(1024).lstrip().startswith(b"%PDF-"):
                    raise ValueError("Invalid PDF header")
            try:
                pages = self.loader.page_count(temporary)
            except Exception:
                raise ValueError("PDF cannot be read") from None
            if pages < 1 or pages > self.max_pages:
                raise ResourceLimit("PDF exceeds page limit or is empty")
            with self.access:
                os.replace(temporary, target)
                try:
                    job, duplicate = self.metadata.register(
                        filename=filename,
                        content_hash=digest.hexdigest(),
                        storage_key=key,
                        size=size,
                        pages=pages,
                        profile=self.profile,
                        version_id=version_id,
                        replace_document=replace_document,
                        legacy_path=legacy_path,
                    )
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
                if duplicate:
                    target.unlink(missing_ok=True)
            self.wake_event.set()
            return {**self.metadata.job(job["id"]), "deduplicated": duplicate}
        finally:
            temporary.unlink(missing_ok=True)

    def ready_builds(self) -> list[str]:
        return self.metadata.ready_builds(self.profile)

    def source(self, version_id: str) -> tuple[dict[str, Any], Path]:
        version = self.metadata.version(version_id)
        if version["deleted_at"]:
            raise KeyError(version_id)
        path = self.path(version["storage_key"])
        if (
            not path.is_file()
            or self.loader.content_hash(path) != version["content_hash"]
        ):
            raise Conflict(
                "Original source is missing or changed; restore it before retry"
            )
        return version, path

    def documents(self) -> list[dict[str, Any]]:
        result = []
        for doc in self.metadata.rows(
            "SELECT * FROM documents WHERE workspace=? AND deleted_at IS NULL "
            "ORDER BY created_at DESC",
            (self.workspace,),
        ):
            latest = self.metadata.rows(
                "SELECT v.*,j.id AS job_id,j.state AS job_state,"
                "j.pages_done,j.total_pages,j.error,j.cancel_requested "
                "FROM versions v JOIN builds b ON b.version_id=v.id "
                "JOIN jobs j ON j.build_id=b.id WHERE v.document_id=? AND b.profile=? "
                "ORDER BY v.ordinal DESC LIMIT 1",
                (doc["id"], self.profile),
            )
            if not latest:
                result.append(
                    {
                        **doc,
                        "state": "needs_reindex",
                        "page_count": 0,
                        "size_bytes": 0,
                        "uploaded_at": doc["created_at"],
                    }
                )
                continue
            version = latest[0]
            result.append(
                {
                    "id": doc["id"],
                    "filename": doc["filename"],
                    "version_id": version["id"],
                    "version": version["ordinal"],
                    "active_version_id": doc["active_version_id"],
                    "size_bytes": version["size_bytes"],
                    "page_count": version["page_count"],
                    "uploaded_at": version["created_at"],
                    "state": version["job_state"],
                    "job_id": version["job_id"],
                    "pages_done": version["pages_done"],
                    "total_pages": version["total_pages"],
                    "error": version["error"],
                    "cancel_requested": bool(version["cancel_requested"]),
                }
            )
        return result

    def delete(self, reference: str) -> dict[str, Any]:
        with self.access:
            job = self.metadata.tombstone(reference)
        self.wake_event.set()
        return job

    def start(self, worker_enabled: bool = True, import_legacy: bool = True) -> None:
        self.metadata.recover()
        self.reconcile()
        if import_legacy:
            imported = {
                row["path"]
                for row in self.metadata.rows("SELECT path FROM legacy_imports")
            }
            for path in sorted(self.root.glob("*")):
                if (
                    path.suffix.lower() != ".pdf"
                    or not path.is_file()
                    or str(path) in imported
                ):
                    continue
                try:
                    with path.open("rb") as stream:
                        self.upload(stream, path.name, legacy_path=str(path))
                except Exception:
                    # Preserve invalid legacy files and log the migration failure.
                    logger.exception("Legacy PDF import failed; original retained")
        if worker_enabled:
            self.thread = Thread(
                target=self._loop, name="vision-ingestion", daemon=False
            )
            self.thread.start()

    def reconcile(self) -> None:
        """Run only under process ownership, before accepting new uploads."""
        referenced = {
            row["storage_key"]
            for row in self.metadata.rows("SELECT storage_key FROM versions")
        }
        for folder, suffix in (("originals", ".pdf"), ("incoming", ".part")):
            for path in self.path(folder).glob("*"):
                try:
                    UUID(path.stem)
                except ValueError:
                    continue
                key = path.relative_to(self.root).as_posix()
                if path.suffix == suffix and key not in referenced:
                    self.path(key).unlink(missing_ok=True)
        ready = self.metadata.rows(
            "SELECT j.* FROM jobs j JOIN builds b ON b.id=j.build_id "
            "JOIN documents d ON d.id=j.document_id WHERE j.kind='ingest' "
            "AND b.state='ready' AND d.deleted_at IS NULL AND d.workspace=?",
            (self.workspace,),
        )
        for job in ready:
            try:
                self.source(job["version_id"])
                if self.store.count_build(job["build_id"]) != job["total_pages"]:
                    raise Conflict("Index is missing or incomplete; retry ingestion")
            except Exception as error:
                self.metadata.finish(job["id"], "failed", str(error))

    def _control(self, job_id: str) -> None:
        if self.stop_event.is_set():
            raise WorkerInterrupted()
        job = self.metadata.job(job_id)
        version = self.metadata.version(job["version_id"])
        if job["cancel_requested"] or version["deleted_at"]:
            raise IngestionCancelled()

    def _ingest(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        self._control(job_id)
        version, path = self.source(job["version_id"])
        self.store.delete_by_payload_filter("build_id", job["build_id"])
        if self.loader.page_count(path) != version["page_count"]:
            raise Conflict("Original page count changed")

        def record(number: int, size: tuple[int, int]) -> None:
            image = self.loader._artifact(path, number)
            thumbnail = self.loader._artifact(path, number, True)
            if image is None or thumbnail is None:
                raise RuntimeError("Durable ingestion requires page artifact storage")
            self.metadata.record_page(
                version["id"],
                number,
                self.loader.dpi,
                image.relative_to(self.root).as_posix(),
                thumbnail.relative_to(self.root).as_posix(),
                *size,
            )

        self.metadata.progress(job_id, "loading_model", 0)
        pipeline = self.pipeline()
        self._control(job_id)
        pipeline.ingest_document(
            path,
            {
                "workspace": self.workspace,
                "document_id": job["document_id"],
                "version_id": version["id"],
                "build_id": job["build_id"],
                "original_filename": version["filename"],
                "profile": self.profile,
            },
            progress=lambda state, done: self.metadata.progress(job_id, state, done),
            check_control=lambda: self._control(job_id),
            page_record=record,
        )
        self._control(job_id)
        if self.store.count_build(job["build_id"]) != version["page_count"]:
            raise Conflict("Vector count does not match the document")
        with self.access:
            self._control(job_id)
            self.metadata.finish(job_id, "ready")

    def _delete(self, job: dict[str, Any]) -> None:
        self.metadata.progress(job["id"], "cleaning", 0)
        with self.access:
            self.store.delete_by_payload_filter("document_id", job["document_id"])
            versions = self.metadata.rows(
                "SELECT * FROM versions WHERE document_id=?", (job["document_id"],)
            )
            for version in versions:
                self.path(version["storage_key"]).unlink(missing_ok=True)
                shared = self.metadata.rows(
                    "SELECT 1 FROM versions v JOIN documents d ON d.id=v.document_id "
                    "WHERE v.content_hash=? AND d.deleted_at IS NULL LIMIT 1",
                    (version["content_hash"],),
                )
                if not shared:
                    cache = self.path("artifacts/" + version["content_hash"])
                    if cache.is_dir():
                        # path() verified containment; hash originates from SHA-256.
                        shutil.rmtree(cache)
            with self.metadata.connection(True) as db:
                db.execute(
                    "DELETE FROM pages WHERE version_id IN "
                    "(SELECT id FROM versions WHERE document_id=?)",
                    (job["document_id"],),
                )
                db.execute(
                    "UPDATE versions SET state='deleted' WHERE document_id=?",
                    (job["document_id"],),
                )
                db.execute(
                    "UPDATE builds SET state='deleted' WHERE version_id IN "
                    "(SELECT id FROM versions WHERE document_id=?)",
                    (job["document_id"],),
                )
                db.execute(
                    "UPDATE jobs SET state='cancelled',updated_at=? "
                    "WHERE document_id=? "
                    "AND kind='ingest' AND state NOT IN ('ready','failed','cancelled')",
                    (now(), job["document_id"]),
                )
                db.execute(
                    "UPDATE documents SET status='deleted',active_version_id=NULL "
                    "WHERE id=?",
                    (job["document_id"],),
                )
            self.metadata.finish(job["id"], "ready")

    def process_one(self) -> bool:
        job = self.metadata.claim()
        if job is None:
            return False
        with trace(job["id"]), stage("ingestion_job", kind=job["kind"]):
            try:
                if job["kind"] == "delete":
                    self._delete(job)
                else:
                    self._ingest(job)
            except WorkerInterrupted:
                self.metadata.finish(
                    job["id"], "uploaded", "Interrupted; queued for recovery"
                )
            except IngestionCancelled:
                try:
                    self.store.delete_by_payload_filter("build_id", job["build_id"])
                    self.metadata.finish(job["id"], "cancelled")
                except Exception:
                    self.metadata.finish(
                        job["id"],
                        "failed",
                        "Cancellation cleanup failed; retry cleanup",
                    )
            except Exception:
                logger.exception("Durable job failed; originals retained")
                self.metadata.finish(
                    job["id"],
                    "failed",
                    "Processing failed; inspect server logs and retry",
                )
        return True

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.process_one():
                    continue
            except Exception:
                logger.exception("Worker poll failed")
            self.wake_event.wait(1)
            self.wake_event.clear()

    def close(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.thread is not None:
            self.thread.join()
        self.owner.close()
