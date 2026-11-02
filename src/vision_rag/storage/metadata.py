"""Authoritative metadata. Vector publication is gated by committed build state."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import NAMESPACE_URL, uuid4, uuid5

ACTIVE = (
    "validating",
    "loading_model",
    "rendering",
    "embedding",
    "indexing",
    "cleaning",
    "extracting",
    "ocr",
)
TERMINAL = ("ready", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, filename TEXT NOT NULL,
 name_key TEXT NOT NULL, created_at TEXT NOT NULL, active_version_id TEXT,
 deleted_at TEXT, status TEXT NOT NULL DEFAULT 'active');
CREATE UNIQUE INDEX IF NOT EXISTS live_names ON documents(workspace,name_key)
 WHERE deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS versions (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 ordinal INTEGER NOT NULL, content_hash TEXT NOT NULL, storage_key TEXT NOT NULL UNIQUE,
 filename TEXT NOT NULL, size_bytes INTEGER NOT NULL, page_count INTEGER NOT NULL,
 created_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'uploaded',
 UNIQUE(document_id,content_hash), UNIQUE(document_id,ordinal));
CREATE TABLE IF NOT EXISTS builds (
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
 profile TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 UNIQUE(version_id,profile));
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 version_id TEXT REFERENCES versions(id), build_id TEXT REFERENCES builds(id),
 kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'uploaded',
 pages_done INTEGER NOT NULL DEFAULT 0, total_pages INTEGER NOT NULL DEFAULT 0,
 cancel_requested INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_build_job ON jobs(build_id) WHERE kind='ingest';
CREATE UNIQUE INDEX IF NOT EXISTS one_delete_job ON jobs(document_id)
 WHERE kind='delete';
CREATE TABLE IF NOT EXISTS pages (
 id TEXT NOT NULL, version_id TEXT NOT NULL REFERENCES versions(id),
 page_number INTEGER NOT NULL, dpi INTEGER NOT NULL, image_key TEXT NOT NULL,
 thumbnail_key TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
 PRIMARY KEY(version_id,page_number,dpi));
CREATE TABLE IF NOT EXISTS legacy_imports (
 path TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id));
CREATE TABLE IF NOT EXISTS page_processing (
 build_id TEXT NOT NULL REFERENCES builds(id), page_number INTEGER NOT NULL,
 revision INTEGER NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
 visual INTEGER NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(build_id,page_number));
CREATE TABLE IF NOT EXISTS text_chunks (
 id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds(id),
 page_number INTEGER NOT NULL, data TEXT NOT NULL, text TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(id UNINDEXED,text);
CREATE TABLE IF NOT EXISTS page_tasks (
 id TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds(id),
 page_number INTEGER NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS pending_page_task
 ON page_tasks(build_id,page_number) WHERE state IN ('uploaded','running');
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identity(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, "vision:" + value))


class Conflict(ValueError):
    pass


class Metadata:
    def __init__(self, path: Path, workspace: str = "local") -> None:
        self.path, self.workspace = path, workspace
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError(
                    "Unsupported metadata schema; restore compatible code"
                )
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                "BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=2; COMMIT;"
            )

    @contextmanager
    def connection(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql: str, values: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, values)]

    def document(self, reference: str, include_deleted: bool = False) -> dict[str, Any]:
        rows = self.rows(
            "SELECT * FROM documents WHERE workspace=? AND (id=? OR name_key=?) "
            + ("" if include_deleted else "AND deleted_at IS NULL ")
            + "ORDER BY created_at DESC LIMIT 1",
            (self.workspace, reference, reference.casefold()),
        )
        if not rows:
            raise KeyError(reference)
        return rows[0]

    def version(self, version_id: str) -> dict[str, Any]:
        rows = self.rows(
            "SELECT v.*,d.workspace,d.deleted_at,d.status AS document_status "
            "FROM versions v JOIN documents d ON d.id=v.document_id "
            "WHERE v.id=? AND d.workspace=?",
            (version_id, self.workspace),
        )
        if not rows:
            raise KeyError(version_id)
        return rows[0]

    def job(self, job_id: str) -> dict[str, Any]:
        rows = self.rows(
            "SELECT j.*,d.filename,CASE WHEN d.deleted_at IS NULL THEN 0 ELSE 1 END "
            "AS document_deleted FROM jobs j JOIN documents d ON d.id=j.document_id "
            "WHERE j.id=? AND d.workspace=?",
            (job_id, self.workspace),
        )
        if not rows:
            raise KeyError(job_id)
        return rows[0]

    def register(
        self,
        *,
        filename: str,
        content_hash: str,
        storage_key: str,
        size: int,
        pages: int,
        profile: str,
        version_id: str,
        replace_document: str | None = None,
        legacy_path: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Deduplicate and create version/build/job in one short transaction."""
        with self.connection(True) as db:
            if replace_document:
                doc = self.document(replace_document)
                document_id = doc["id"]
                duplicate = db.execute(
                    "SELECT v.id FROM versions v WHERE document_id=? "
                    "AND content_hash=?",
                    (document_id, content_hash),
                ).fetchone()
            else:
                duplicate = db.execute(
                    "SELECT v.id,v.document_id FROM versions v JOIN documents d "
                    "ON d.id=v.document_id WHERE d.workspace=? "
                    "AND d.deleted_at IS NULL "
                    "AND v.content_hash=? ORDER BY v.created_at LIMIT 1",
                    (self.workspace, content_hash),
                ).fetchone()
                document_id = duplicate["document_id"] if duplicate else str(uuid4())
            if duplicate:
                existing = db.execute(
                    "SELECT j.* FROM jobs j JOIN builds b ON b.id=j.build_id "
                    "WHERE b.version_id=? AND b.profile=?",
                    (duplicate["id"], profile),
                ).fetchone()
                if existing:
                    if legacy_path:
                        db.execute(
                            "INSERT OR IGNORE INTO legacy_imports VALUES (?,?)",
                            (legacy_path, document_id),
                        )
                    return dict(existing), True
                # A changed profile is never silently exposed as an existing index.
                raise Conflict("Existing content needs an explicit index migration")
            if not replace_document:
                if db.execute(
                    "SELECT 1 FROM documents WHERE workspace=? AND "
                    "name_key=? AND deleted_at IS NULL",
                    (self.workspace, filename.casefold()),
                ).fetchone():
                    raise Conflict(
                        "Filename exists; upload an explicit document version"
                    )
                db.execute(
                    "INSERT INTO documents(id,workspace,filename,name_key,created_at) "
                    "VALUES (?,?,?,?,?)",
                    (document_id, self.workspace, filename, filename.casefold(), now()),
                )
            ordinal = db.execute(
                "SELECT COALESCE(MAX(ordinal),0)+1 FROM versions WHERE document_id=?",
                (document_id,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO versions(id,document_id,ordinal,content_hash,storage_key,"
                "filename,size_bytes,page_count,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    document_id,
                    ordinal,
                    content_hash,
                    storage_key,
                    filename,
                    size,
                    pages,
                    now(),
                ),
            )
            build_id = identity(version_id + ":" + profile)
            job_id = str(uuid4())
            db.execute(
                "INSERT INTO builds(id,version_id,profile) VALUES (?,?,?)",
                (build_id, version_id, profile),
            )
            db.execute(
                "INSERT INTO jobs(id,document_id,version_id,build_id,kind,total_pages,"
                "created_at,updated_at) VALUES (?,?,?,?,'ingest',?,?,?)",
                (job_id, document_id, version_id, build_id, pages, now(), now()),
            )
            if legacy_path:
                db.execute(
                    "INSERT OR IGNORE INTO legacy_imports VALUES (?,?)",
                    (legacy_path, document_id),
                )
            return dict(
                db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            ), False

    def claim(self) -> dict[str, Any] | None:
        with self.connection(True) as db:
            row = db.execute(
                "SELECT j.* FROM jobs j JOIN documents d ON d.id=j.document_id "
                "WHERE d.workspace=? AND j.state='uploaded' "
                "ORDER BY CASE j.kind WHEN 'delete' THEN 0 ELSE 1 END,"
                "j.created_at LIMIT 1",
                (self.workspace,),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET state='validating',attempts=attempts+1,"
                "pages_done=0,error=NULL,updated_at=? WHERE id=?",
                (now(), row["id"]),
            )
            if row["build_id"]:
                db.execute(
                    "UPDATE builds SET state='building' WHERE id=?", (row["build_id"],)
                )
            return dict(row)

    def progress(self, job_id: str, state: str, done: int) -> None:
        with self.connection(True) as db:
            db.execute(
                "UPDATE jobs SET state=?,pages_done=?,updated_at=? WHERE id=?",
                (state, done, now(), job_id),
            )

    def finish(self, job_id: str, state: str, error: str | None = None) -> None:
        with self.connection(True) as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if state == "ready" and job["kind"] == "ingest":
                if job["pages_done"] != job["total_pages"]:
                    raise Conflict("Cannot publish an incomplete build")
                deleted = db.execute(
                    "SELECT deleted_at FROM documents WHERE id=?", (job["document_id"],)
                ).fetchone()[0]
                if deleted or job["cancel_requested"]:
                    raise Conflict("Job was cancelled before publication")
                db.execute(
                    "UPDATE documents SET active_version_id=? WHERE id=? "
                    "AND (active_version_id IS NULL OR "
                    "(SELECT ordinal FROM versions WHERE id=active_version_id) <= "
                    "(SELECT ordinal FROM versions WHERE id=?))",
                    (job["version_id"], job["document_id"], job["version_id"]),
                )
            if job["build_id"]:
                db.execute(
                    "UPDATE builds SET state=? WHERE id=?", (state, job["build_id"])
                )
                db.execute(
                    "UPDATE versions SET state=? WHERE id=?", (state, job["version_id"])
                )
            db.execute(
                "UPDATE jobs SET state=?,error=?,updated_at=? WHERE id=?",
                (state, error, now(), job_id),
            )

    def ready_builds(self, profile: str) -> list[str]:
        return [
            row["id"]
            for row in self.rows(
                "SELECT b.id FROM builds b JOIN versions v ON v.id=b.version_id "
                "JOIN documents d ON d.active_version_id=v.id WHERE d.workspace=? "
                "AND d.deleted_at IS NULL AND b.state='ready' AND b.profile=?",
                (self.workspace, profile),
            )
        ]

    def retry(self, job_id: str) -> dict[str, Any]:
        job = self.job(job_id)
        if job["state"] not in ("failed", "cancelled"):
            raise Conflict("Only failed or cancelled jobs can be retried")
        if job["kind"] == "ingest":
            self.document(job["document_id"])
        # A failed cancellation first retries cleanup; a cancelled job starts afresh.
        cancel = int(job["state"] == "failed" and job["cancel_requested"])
        with self.connection(True) as db:
            changed = db.execute(
                "UPDATE jobs SET state='uploaded',cancel_requested=?,error=NULL,"
                "pages_done=0,updated_at=? WHERE id=? "
                "AND state IN ('failed','cancelled')",
                (cancel, now(), job_id),
            ).rowcount
            if changed != 1:
                raise Conflict("Job state changed; refresh before retrying")
            if job["build_id"]:
                db.execute(
                    "UPDATE builds SET state='pending' WHERE id=?", (job["build_id"],)
                )
        return self.job(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.job(job_id)
        if job["kind"] != "ingest" or job["state"] in TERMINAL:
            raise Conflict("Only unfinished ingestion can be cancelled")
        with self.connection(True) as db:
            changed = db.execute(
                "UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=? "
                "AND state NOT IN ('ready','failed','cancelled')",
                (now(), job_id),
            ).rowcount
            if changed != 1:
                raise Conflict("Job completed before cancellation")
        return self.job(job_id)

    def tombstone(self, reference: str) -> dict[str, Any]:
        doc = self.document(reference, include_deleted=True)
        with self.connection(True) as db:
            db.execute(
                "UPDATE documents SET deleted_at=COALESCE(deleted_at,?),"
                "status='deleting' WHERE id=?",
                (now(), doc["id"]),
            )
            db.execute(
                "UPDATE jobs SET cancel_requested=1 WHERE document_id=? "
                "AND kind='ingest' AND state NOT IN ('ready','failed','cancelled')",
                (doc["id"],),
            )
            job_id = identity(doc["id"] + ":delete")
            db.execute(
                "INSERT INTO jobs(id,document_id,kind,created_at,updated_at) "
                "VALUES (?,?,'delete',?,?) ON CONFLICT(id) DO NOTHING",
                (job_id, doc["id"], now(), now()),
            )
        return self.job(job_id)

    def recover(self) -> None:
        with self.connection(True) as db:
            db.execute(
                "UPDATE jobs SET state='uploaded',"
                "error='Interrupted; queued for recovery',"
                "updated_at=? WHERE state IN "
                "('validating','loading_model','rendering','embedding',"
                "'indexing','cleaning','extracting','ocr') "
                "AND document_id IN (SELECT id FROM documents WHERE workspace=?)",
                (now(), self.workspace),
            )
            db.execute(
                "UPDATE builds SET state='pending' WHERE state='building' AND id IN "
                "(SELECT build_id FROM jobs WHERE state='uploaded')"
            )

    def record_page(
        self,
        version: str,
        number: int,
        dpi: int,
        image_key: str,
        thumbnail_key: str,
        width: int,
        height: int,
    ) -> None:
        with self.connection(True) as db:
            db.execute(
                "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?)",
                (
                    identity(version + ":page:" + str(number)),
                    version,
                    number,
                    dpi,
                    image_key,
                    thumbnail_key,
                    width,
                    height,
                ),
            )
