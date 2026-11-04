"""Durable staged retrieval indexes with atomic activation and retained rollback."""

import hashlib
import json
import logging
from typing import Any
from uuid import uuid4

from vision_rag.ingest.text import Block, chunks, inspect_page
from vision_rag.storage.metadata import Conflict, Metadata, identity, now
from vision_rag.vector_stores.retrieval_store import RetrievalStore

logger = logging.getLogger(__name__)


class IndexInterrupted(Exception):
    pass


class RetrievalIndexes:
    def __init__(
        self, library: Any, models: Any, specification: dict[str, Any]
    ) -> None:
        self.library, self.models, self.spec = library, models, specification
        self.meta: Metadata = library.metadata
        self.profile = hashlib.sha256(
            json.dumps(specification, sort_keys=True).encode()
        ).hexdigest()

    def snapshot(self) -> str:
        builds = self.source_builds()
        data = []
        for build in sorted(builds):
            version = self.meta.rows(
                "SELECT v.id,v.content_hash,v.page_count FROM builds b "
                "JOIN versions v ON v.id=b.version_id WHERE b.id=?",
                (build,),
            )[0]
            pages = self.meta.rows(
                "SELECT page_number,revision,state,visual FROM page_processing "
                "WHERE build_id=? ORDER BY page_number",
                (build,),
            )
            data.append([build, version, pages])
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def source_builds(self) -> list[str]:
        if self.library.reset_pending():
            return []
        rows = self.meta.rows(
            "SELECT b.id,b.version_id FROM builds b JOIN versions v ON "
            "v.id=b.version_id "
            "JOIN documents d ON d.active_version_id=v.id WHERE d.workspace=? "
            "AND d.deleted_at IS NULL AND b.state='ready' "
            "ORDER BY CASE WHEN b.profile=? THEN 0 ELSE 1 END,b.id",
            (self.library.workspace, self.library.profile),
        )
        chosen: dict[str, str] = {}
        for row in rows:
            chosen.setdefault(row["version_id"], row["id"])
        return list(chosen.values())

    def row(self, key: str) -> dict[str, Any]:
        rows = self.meta.rows(
            "SELECT * FROM retrieval_indexes WHERE id=? AND workspace=?",
            (key, self.library.workspace),
        )
        if not rows:
            raise KeyError(key)
        return rows[0]

    def revisions(self) -> list[dict[str, Any]]:
        return self.meta.rows(
            "SELECT * FROM retrieval_indexes WHERE workspace=? ORDER BY "
            "created_at DESC",
            (self.library.workspace,),
        )

    def store(self, row: dict[str, Any]) -> RetrievalStore:
        spec = json.loads(row["specification"])
        return RetrievalStore(
            self.library.store,
            row["storage_id"],
            spec["text_dimensions"],
            spec["visual_dimensions"],
        )

    def queue(self, activate: bool = True) -> dict[str, Any]:
        self.library.check_available()
        if not self.source_builds():
            raise Conflict("Wait for at least one document to finish ingestion")
        signature = self.snapshot()
        for row in self.revisions():
            if (
                row["state"] in ("queued", "building")
                and row["profile"] == self.profile
            ):
                return row
        key = str(uuid4())
        with self.meta.connection(True) as db:
            db.execute(
                "INSERT INTO retrieval_indexes(id,workspace,profile,storage_id,"
                "specification,state,snapshot,"
                "auto_activate,created_at,updated_at) VALUES "
                "(?,?,?,?,?,'queued',?,?,?,?)",
                (
                    key,
                    self.library.workspace,
                    self.profile,
                    str(uuid4()),
                    json.dumps(self.spec),
                    signature,
                    int(activate),
                    now(),
                    now(),
                ),
            )
        self.library.wake_event.set()
        return self.row(key)

    def active(self) -> dict[str, Any] | None:
        key = self.meta.setting("retrieval_active")
        if not key or self.library.reset_pending():
            return None
        row = self.row(key)
        return row if row["state"] == "ready" else None

    def activate(self, key: str) -> dict[str, Any]:
        row = self.row(key)
        if row["state"] != "ready" or row["snapshot"] != self.snapshot():
            raise Conflict(
                "Index is incomplete or its source snapshot has changed; rebuild"
            )
        store = self.store(row)
        for channel in ("text", "visual"):
            expected = self.meta.rows(
                "SELECT COUNT(*) AS n FROM retrieval_items WHERE index_id=? AND kind=?",
                (key, channel),
            )[0]["n"]
            if store.count(channel) != expected:
                raise Conflict("Index vectors are incomplete; rebuild")
        with self.meta.connection(True) as db:
            old = self.meta.setting("retrieval_active")
            for setting, value in (
                ("retrieval_previous", old or ""),
                ("retrieval_active", key),
            ):
                db.execute(
                    "INSERT INTO app_state VALUES (?,?,?) ON CONFLICT(workspace,key) "
                    "DO UPDATE SET value=excluded.value",
                    (self.library.workspace, setting, value),
                )
        return row

    def recover(self) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "UPDATE retrieval_indexes SET "
                "state='queued',error='Interrupted; rebuilding',updated_at=? "
                "WHERE workspace=? AND state='building'",
                (now(), self.library.workspace),
            )
        lost_active = False
        for row in self.revisions():
            if row["state"] != "ready":
                continue
            try:
                for channel in ("text", "visual"):
                    expected = self.meta.rows(
                        "SELECT COUNT(*) AS n FROM retrieval_items "
                        "WHERE index_id=? AND kind=?",
                        (row["id"], channel),
                    )[0]["n"]
                    if self.store(row).count(channel) != expected:
                        raise Conflict("Retrieval vectors are incomplete")
            except Exception:
                self._finish(
                    row["id"], "failed", "Retrieval storage is missing; rebuild"
                )
                lost_active |= self.meta.setting("retrieval_active") == row["id"]
        if lost_active and self.source_builds():
            self.queue()

    def eligible(
        self,
        row: dict[str, Any],
        documents: list[str] | None = None,
        pages: tuple[int, int] | None = None,
    ) -> dict[str, list[str]]:
        rows = self.meta.rows(
            "SELECT r.* FROM retrieval_items r JOIN documents d ON d.id=r.document_id "
            "JOIN builds b ON b.id=r.build_id LEFT JOIN page_processing p "
            "ON p.build_id=r.build_id AND p.page_number=r.page_number "
            "WHERE r.index_id=? AND d.workspace=? AND d.deleted_at IS NULL "
            "AND r.build_id IN (SELECT value FROM json_each(?)) "
            "AND d.active_version_id=r.version_id AND b.state='ready' "
            "AND ((r.revision=0 AND p.page_number IS NULL) OR "
            "(p.revision=r.revision AND p.state='ready'))",
            (row["id"], self.library.workspace, json.dumps(self.source_builds())),
        )
        return {
            kind: [
                r["id"]
                for r in rows
                if r["kind"] == kind
                and (documents is None or r["document_id"] in documents)
                and (pages is None or pages[0] <= r["page_number"] <= pages[1])
            ]
            for kind in ("text", "visual")
        }

    def _control(self, key: str) -> None:
        if (
            self.library.stop_event.is_set()
            or self.library.maintenance_requested.is_set()
        ):
            raise IndexInterrupted()
        if self.row(key)["state"] == "cancelled":
            raise IndexInterrupted()

    def _item(
        self, key: str, point: str, kind: str, base: dict[str, Any], revision: int
    ) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "INSERT OR REPLACE INTO retrieval_items VALUES (?,?,?,?,?,?,?,?)",
                (
                    key,
                    point,
                    kind,
                    base["document_id"],
                    base["version_id"],
                    base["build_id"],
                    base["page_number"],
                    revision,
                ),
            )
            if kind == "text":
                db.execute(
                    "INSERT INTO retrieval_search VALUES (?,?,?)",
                    (key, point, base["text"]),
                )

    def build(self, row: dict[str, Any]) -> None:
        key = row["id"]
        spec = json.loads(row["specification"])
        store = self.store(row)
        store.drop()
        # A new attempt ID avoids Windows local Qdrant reopening deleted files.
        row["storage_id"] = str(uuid4())
        with self.meta.connection(True) as db:
            db.execute(
                "UPDATE retrieval_indexes SET storage_id=? WHERE id=?",
                (row["storage_id"], key),
            )
        store = self.store(row)
        store.create()
        with self.meta.connection(True) as db:
            db.execute("DELETE FROM retrieval_items WHERE index_id=?", (key,))
            db.execute("DELETE FROM retrieval_search WHERE index_id=?", (key,))
        done = 0
        for build in self.source_builds():
            version_id = self.meta.rows(
                "SELECT version_id FROM builds WHERE id=?", (build,)
            )[0]["version_id"]
            version, path = self.library.source(version_id)
            for number in range(1, version["page_count"] + 1):
                self._control(key)
                records = self.library.processing.pages(build, number=number)
                record = records[0] if records else None
                if record and record["state"] != "ready":
                    raise Conflict(
                        "A page is still being processed; retry indexing later"
                    )
                revision = record["revision"] if record else 0
                visual = bool(record["visual"]) if record else True
                raw_chunks = self.meta.rows(
                    "SELECT id,data,text FROM text_chunks WHERE build_id=? AND "
                    "page_number=?",
                    (build, number),
                )
                if not record:
                    inspection = inspect_page(path, number)
                    if inspection.quality in ("usable", "uncertain"):
                        raw_chunks = [
                            {
                                "id": identity(f"{build}:{number}:native:{i}"),
                                "data": json.dumps(c),
                                "text": c["text"],
                            }
                            for i, c in enumerate(
                                chunks(
                                    inspection.blocks
                                    or [
                                        Block(
                                            inspection.native_text,
                                            (0, 0, inspection.width, inspection.height),
                                        )
                                    ]
                                )
                            )
                        ]
                base = {
                    "version_id": version_id,
                    "document_id": version["document_id"],
                    "build_id": build,
                    "page_number": number,
                    "original_filename": version["filename"],
                }
                for chunk in raw_chunks:
                    for offset, part in enumerate(
                        self.models.split_text(spec, chunk["text"])
                    ):
                        self._control(key)
                        point = identity(f"{key}:text:{chunk['id']}:{offset}")
                        vector = self.models.encode_text(spec, [part])[0]
                        payload = {
                            **base,
                            "text": part,
                            "chunk_id": chunk["id"],
                            "heading": json.loads(chunk["data"]).get("heading"),
                        }
                        store.put_text([point], [vector], [payload])
                        self._item(key, point, "text", payload, revision)
                if visual:
                    self._control(key)
                    point = identity(f"{key}:visual:{build}:{number}")
                    with self.library.loader.load_page(path, number) as image:
                        tokens = self.models.encode_visual(spec, [image], True)[0]
                    store.put_visual(point, tokens, base)
                    self._item(key, point, "visual", base, revision)
                done += 1
                with self.meta.connection(True) as db:
                    db.execute(
                        "UPDATE retrieval_indexes SET pages_done=?,updated_at=? "
                        "WHERE id=?",
                        (done, now(), key),
                    )
        self._control(key)
        if row["snapshot"] != self.snapshot():
            raise Conflict("Library changed during indexing; rebuild the new snapshot")
        with self.meta.connection(True) as db:
            db.execute(
                "UPDATE retrieval_indexes SET "
                "state='ready',error=NULL,updated_at=? WHERE id=?",
                (now(), key),
            )
        if row["auto_activate"]:
            with self.library.access:
                self.activate(key)

    def process_one(self) -> bool:
        rows = [r for r in self.revisions() if r["state"] == "queued"]
        if not rows:
            signature = self.snapshot()
            if self.source_builds() and not any(
                r["snapshot"] == signature and r["profile"] == self.profile
                for r in self.revisions()
            ):
                self.queue()
                rows = [self.revisions()[0]]
        if not rows:
            return False
        row = rows[-1]
        row["snapshot"] = self.snapshot()
        with self.meta.connection(True) as db:
            db.execute(
                "UPDATE retrieval_indexes SET "
                "state='building',pages_done=0,snapshot=? WHERE id=?",
                (row["snapshot"], row["id"]),
            )
        try:
            self.build(row)
        except IndexInterrupted:
            state = (
                "cancelled" if self.row(row["id"])["state"] == "cancelled" else "queued"
            )
            self._finish(
                row["id"], state, "Interrupted; partial index remains unpublished"
            )
        except Exception as error:
            logger.exception("Retrieval index failed; previous index retained")
            self._finish(row["id"], "failed", str(error)[:300])
        return True

    def _finish(self, key: str, state: str, error: str | None) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "UPDATE retrieval_indexes SET state=?,error=?,updated_at=? WHERE id=?",
                (state, error, now(), key),
            )

    def cancel(self, key: str) -> None:
        row = self.row(key)
        if row["state"] not in ("queued", "building"):
            raise Conflict("Only unfinished indexing can be cancelled")
        self._finish(key, "cancelled", "Cancelled by user")

    def remove_document(self, document: str) -> None:
        for row in self.revisions():
            self.store(row).remove_document(document)
        with self.meta.connection(True) as db:
            db.execute(
                "DELETE FROM retrieval_search WHERE point_id IN "
                "(SELECT id FROM retrieval_items WHERE document_id=? AND index_id IN "
                "(SELECT id FROM retrieval_indexes WHERE workspace=?))",
                (document, self.library.workspace),
            )
            db.execute(
                "DELETE FROM retrieval_items WHERE document_id=? AND index_id IN "
                "(SELECT id FROM retrieval_indexes WHERE workspace=?)",
                (document, self.library.workspace),
            )

    def clear(self) -> None:
        for row in self.revisions():
            self.store(row).drop()
        with self.meta.connection(True) as db:
            db.execute(
                "DELETE FROM retrieval_search WHERE index_id IN "
                "(SELECT id FROM retrieval_indexes WHERE workspace=?)",
                (self.library.workspace,),
            )
            db.execute(
                "DELETE FROM retrieval_items WHERE index_id IN "
                "(SELECT id FROM retrieval_indexes WHERE workspace=?)",
                (self.library.workspace,),
            )
            db.execute(
                "DELETE FROM retrieval_indexes WHERE workspace=?",
                (self.library.workspace,),
            )
