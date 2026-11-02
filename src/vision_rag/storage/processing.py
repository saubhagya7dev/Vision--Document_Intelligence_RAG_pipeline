"""Page publication, lexical discovery, and durable page override tasks."""

import json
from typing import Any
from uuid import uuid4

from vision_rag.ingest.text import MODES, lexical_terms
from vision_rag.storage.metadata import Conflict, Metadata, identity, now


class ProcessingMetadata:
    def __init__(self, metadata: Metadata) -> None:
        self.meta = metadata

    def pages(self, build: str) -> list[dict[str, Any]]:
        return [
            {**row, "data": json.loads(row["data"])}
            for row in self.meta.rows(
                "SELECT * FROM page_processing WHERE build_id=? ORDER BY page_number",
                (build,),
            )
        ]

    def publish(
        self,
        build: str,
        number: int,
        mode: str,
        data: dict[str, Any],
        chunk_list: list[dict[str, Any]],
    ) -> None:
        with self.meta.connection(True) as db:
            revision = db.execute(
                "SELECT revision FROM page_processing WHERE build_id=? AND page_number=?",
                (build, number),
            ).fetchone()
            revision = revision[0] + 1 if revision else 1
            db.execute(
                "DELETE FROM chunk_search WHERE id IN (SELECT id FROM text_chunks "
                "WHERE build_id=? AND page_number=?)",
                (build, number),
            )
            db.execute(
                "DELETE FROM text_chunks WHERE build_id=? AND page_number=?",
                (build, number),
            )
            for offset, chunk in enumerate(chunk_list):
                key = identity(
                    f"{build}:page:{number}:revision:{revision}:chunk:{offset}"
                )
                db.execute(
                    "INSERT INTO text_chunks VALUES (?,?,?,?,?)",
                    (key, build, number, json.dumps(chunk), chunk["text"]),
                )
                db.execute(
                    "INSERT INTO chunk_search VALUES (?,?)", (key, chunk["text"])
                )
            db.execute(
                "INSERT INTO page_processing VALUES (?,?,?,?,'ready',?,?,?) "
                "ON CONFLICT(build_id,page_number) DO UPDATE SET "
                "revision=excluded.revision,mode=excluded.mode,state='ready',"
                "visual=excluded.visual,data=excluded.data,updated_at=excluded.updated_at",
                (
                    build,
                    number,
                    revision,
                    mode,
                    int(data["visual"]),
                    json.dumps(data),
                    now(),
                ),
            )

    def clear(self, build: str) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "DELETE FROM chunk_search WHERE id IN "
                "(SELECT id FROM text_chunks WHERE build_id=?)",
                (build,),
            )
            db.execute("DELETE FROM text_chunks WHERE build_id=?", (build,))
            db.execute("DELETE FROM page_processing WHERE build_id=?", (build,))

    def expected_vectors(self, build: str, fallback: int) -> int:
        pages = self.pages(build)
        return sum(row["visual"] for row in pages) if pages else fallback

    def hidden_points(self, profile: str) -> list[str]:
        rows = self.meta.rows(
            "SELECT p.build_id,p.page_number FROM page_processing p JOIN builds b "
            "ON b.id=p.build_id JOIN versions v ON v.id=b.version_id JOIN documents d "
            "ON d.id=v.document_id WHERE d.workspace=? AND b.profile=? "
            "AND (p.state!='ready' OR p.visual=0)",
            (self.meta.workspace, profile),
        )
        return [identity(f"{r['build_id']}:point:{r['page_number']}") for r in rows]

    def search(self, query: str, profile: str, limit: int) -> list[dict[str, Any]]:
        terms = lexical_terms(query)
        if not terms:
            return []
        # Quote terms; no user-provided FTS operators, SQL, or filesystem paths.
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        rows = self.meta.rows(
            "SELECT c.id,c.build_id,c.page_number,c.text,c.data,v.id AS version_id,"
            "v.document_id,v.filename,chunk_search.rank AS lexical_rank "
            "FROM chunk_search JOIN text_chunks c ON c.id=chunk_search.id "
            "JOIN page_processing p ON p.build_id=c.build_id AND p.page_number=c.page_number "
            "JOIN builds b ON b.id=c.build_id JOIN versions v ON v.id=b.version_id "
            "JOIN documents d ON d.active_version_id=v.id WHERE chunk_search MATCH ? "
            "AND d.workspace=? AND d.deleted_at IS NULL AND b.profile=? "
            "AND b.state='ready' AND p.state='ready' ORDER BY lexical_rank LIMIT ?",
            (match, self.meta.workspace, profile, min(limit * 4, 200)),
        )
        seen: set[tuple[str, int]] = set()
        results = []
        for row in rows:
            key = (row["version_id"], row["page_number"])
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "id": row["id"],
                    "score": None,
                    "payload": {
                        "build_id": row["build_id"],
                        "version_id": row["version_id"],
                        "document_id": row["document_id"],
                        "page_number": row["page_number"],
                        "original_filename": row["filename"],
                        "channel": "lexical",
                        "text": row["text"],
                        "lexical_rank": row["lexical_rank"],
                    },
                }
            )
            if len(results) >= limit:
                break
        return results

    def task(self, task_id: str) -> dict[str, Any]:
        rows = self.meta.rows(
            "SELECT t.*,v.id AS version_id,v.document_id FROM page_tasks t "
            "JOIN builds b ON b.id=t.build_id JOIN versions v ON v.id=b.version_id "
            "JOIN documents d ON d.id=v.document_id WHERE t.id=? "
            "AND d.workspace=? AND d.deleted_at IS NULL",
            (task_id, self.meta.workspace),
        )
        if not rows:
            raise KeyError(task_id)
        return rows[0]

    def enqueue(self, build: str, number: int, mode: str) -> dict[str, Any]:
        if mode not in MODES:
            raise ValueError("Unsupported processing mode")
        with self.meta.connection(True) as db:
            row = db.execute(
                "SELECT b.state,v.page_count,d.deleted_at FROM builds b "
                "JOIN versions v ON v.id=b.version_id JOIN documents d ON d.id=v.document_id "
                "WHERE b.id=? AND d.workspace=?",
                (build, self.meta.workspace),
            ).fetchone()
            if row is None or row["deleted_at"]:
                raise KeyError(build)
            if row["state"] != "ready":
                raise Conflict("Complete ingestion before overriding a page")
            if not 1 <= number <= row["page_count"]:
                raise IndexError(number)
            if db.execute(
                "SELECT 1 FROM page_tasks WHERE build_id=? AND page_number=? "
                "AND state IN ('uploaded','running')",
                (build, number),
            ).fetchone():
                raise Conflict("A task is already queued for this page")
            key = str(uuid4())
            db.execute(
                "INSERT INTO page_tasks VALUES (?,?,?,?,'uploaded',0,NULL,?,?)",
                (key, build, number, mode, now(), now()),
            )
            # Even legacy pages must become hidden as soon as the task is accepted.
            db.execute(
                "INSERT INTO page_processing VALUES (?,?,0,?,'pending',0,'{}',?) "
                "ON CONFLICT(build_id,page_number) DO UPDATE SET state='pending'",
                (build, number, mode, now()),
            )
        return self.task(key)

    def claim(self) -> dict[str, Any] | None:
        with self.meta.connection(True) as db:
            row = db.execute(
                "SELECT t.id FROM page_tasks t JOIN builds b ON b.id=t.build_id "
                "JOIN versions v ON v.id=b.version_id JOIN documents d ON d.id=v.document_id "
                "WHERE t.state='uploaded' AND d.deleted_at IS NULL AND d.workspace=? "
                "ORDER BY t.created_at LIMIT 1",
                (self.meta.workspace,),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE page_tasks SET state='running',attempts=attempts+1,updated_at=? "
                "WHERE id=?",
                (now(), row["id"]),
            )
        return self.task(row["id"])

    def finish_task(self, task: str, state: str, error: str | None = None) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "UPDATE page_tasks SET state=?,error=?,updated_at=? WHERE id=?",
                (state, error, now(), task),
            )

    def recover(self) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "UPDATE page_tasks SET state='uploaded',updated_at=? "
                "WHERE state='running' AND build_id IN (SELECT b.id FROM builds b "
                "JOIN versions v ON v.id=b.version_id JOIN documents d ON d.id=v.document_id "
                "WHERE d.workspace=?)",
                (now(), self.meta.workspace),
            )
