"""Workspace-scoped conversations, immutable turn scope and ordered events."""

import json
import sqlite3
from typing import Any
from uuid import uuid4

from vision_rag.storage.metadata import Conflict, Metadata, now

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class Conversations:
    def __init__(self, metadata: Metadata) -> None:
        self.meta = metadata

    def all(self) -> list[dict[str, Any]]:
        return [
            self.decode(r)
            for r in self.meta.rows(
                "SELECT * FROM conversations WHERE workspace=? ORDER BY updated_at DESC,id",
                (self.meta.workspace,),
            )
        ]

    @staticmethod
    def decode(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "document_ids": json.loads(row["document_ids"]),
            "viewer": json.loads(row["viewer"]),
        }

    def get(self, key: str) -> dict[str, Any]:
        rows = self.meta.rows(
            "SELECT * FROM conversations WHERE id=? AND workspace=?",
            (key, self.meta.workspace),
        )
        if not rows:
            raise KeyError(key)
        result = self.decode(rows[0])
        result["messages"] = [
            self.message(r["id"])
            for r in self.meta.rows(
                "SELECT id FROM messages WHERE conversation_id=? ORDER BY created_at,id",
                (key,),
            )
        ]
        return result

    def create(self, title: str, documents: list[str] | None) -> dict[str, Any]:
        key, timestamp = str(uuid4()), now()
        with self.meta.connection(True) as db:
            db.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,?,?,?)",
                (
                    key,
                    self.meta.workspace,
                    title,
                    json.dumps(documents),
                    "{}",
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(key)

    def update(self, key: str, values: dict[str, Any]) -> dict[str, Any]:
        self.get(key)
        with self.meta.connection(True) as db:
            for field in ("title", "document_ids", "viewer"):
                if field in values:
                    value = values[field]
                    if field != "title":
                        value = json.dumps(value)
                    db.execute(
                        f"UPDATE conversations SET {field}=?,updated_at=? "
                        "WHERE id=? AND workspace=?",
                        (value, now(), key, self.meta.workspace),
                    )
        return self.get(key)

    def delete(self, key: str) -> None:
        self.get(key)
        with self.meta.connection(True) as db:
            db.execute(
                "DELETE FROM conversations WHERE id=? AND workspace=?",
                (key, self.meta.workspace),
            )

    def message(self, key: str) -> dict[str, Any]:
        rows = self.meta.rows(
            "SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE m.id=? AND c.workspace=?",
            (key, self.meta.workspace),
        )
        if not rows:
            raise KeyError(key)
        row = rows[0]
        return {
            **row,
            "request": json.loads(row["request"]),
            "result": json.loads(row["result"]) if row["result"] else None,
        }

    def start(self, key: str, request: dict[str, Any]) -> dict[str, Any]:
        conversation = self.get(key)
        request = {**request, "document_ids": conversation["document_ids"]}
        previous = conversation["messages"][-1:] or [None]
        request["previous_question"] = (
            previous[0]["question"][:2000] if previous[0] else None
        )
        identity, timestamp = str(uuid4()), now()
        try:
            with self.meta.connection(True) as db:
                db.execute(
                    "INSERT INTO messages(id,conversation_id,question,request,state,"
                    "created_at,updated_at) VALUES (?,?,?,?,'queued',?,?)",
                    (
                        identity,
                        key,
                        request["query"],
                        json.dumps(request),
                        timestamp,
                        timestamp,
                    ),
                )
                db.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?", (timestamp, key)
                )
        except sqlite3.IntegrityError as error:
            raise Conflict(
                "A question is already running in this conversation"
            ) from error
        self.event(identity, "progress", {"stage": "queued"})
        return self.message(identity)

    def event(self, key: str, kind: str, data: dict[str, Any]) -> None:
        with self.meta.connection(True) as db:
            row = db.execute(
                "SELECT m.state FROM messages m JOIN conversations c "
                "ON c.id=m.conversation_id WHERE m.id=? AND c.workspace=?",
                (key, self.meta.workspace),
            ).fetchone()
            if not row or row["state"] in TERMINAL:
                return
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM message_events "
                "WHERE message_id=?",
                (key,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO message_events VALUES (?,?,?,?)",
                (key, sequence, kind, json.dumps(data)),
            )

    def events(self, key: str, after: int = 0) -> list[dict[str, Any]]:
        self.message(key)
        return [
            {**r, "data": json.loads(r["data"])}
            for r in self.meta.rows(
                "SELECT sequence,type,data FROM message_events WHERE message_id=? "
                "AND sequence>? ORDER BY sequence LIMIT 100",
                (key, after),
            )
        ]

    def finish(
        self,
        key: str,
        state: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        # Final event and authoritative answer publish together, including cancellation.
        with self.meta.connection(True) as db:
            row = db.execute(
                "SELECT m.* FROM messages m JOIN conversations c "
                "ON c.id=m.conversation_id WHERE m.id=? AND c.workspace=?",
                (key, self.meta.workspace),
            ).fetchone()
            if not row or row["state"] in TERMINAL:
                return
            if row["cancel_requested"]:
                state, result, error = "cancelled", None, "Question cancelled"
            kind = "final-answer" if state == "completed" else "error"
            payload = {"state": state, "result": result, "message": error}
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM message_events "
                "WHERE message_id=?",
                (key,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO message_events VALUES (?,?,?,?)",
                (key, sequence, kind, json.dumps(payload)),
            )
            db.execute(
                "UPDATE messages SET state=?,result=?,error=?,updated_at=? WHERE id=?",
                (state, json.dumps(result) if result else None, error, now(), key),
            )

    def cancel(self, key: str) -> dict[str, Any]:
        row = self.message(key)
        if row["state"] not in TERMINAL:
            with self.meta.connection(True) as db:
                db.execute("UPDATE messages SET cancel_requested=1 WHERE id=?", (key,))
        return self.message(key)

    def cancelled(self, key: str) -> bool:
        try:
            row = self.message(key)
            return bool(row["cancel_requested"] or row["state"] in TERMINAL)
        except KeyError:
            return True

    def recover(self) -> None:
        for row in self.meta.rows(
            "SELECT m.id FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE c.workspace=? AND m.state IN ('queued','running')",
            (self.meta.workspace,),
        ):
            self.finish(
                row["id"], "interrupted", error="Server restarted; retry the question"
            )

    def clear(self) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "DELETE FROM conversations WHERE workspace=?", (self.meta.workspace,)
            )
