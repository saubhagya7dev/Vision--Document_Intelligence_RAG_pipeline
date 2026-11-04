"""Immutable finding content; saving and user review do not rewrite evidence."""

import hashlib
import json
from typing import Any
from uuid import uuid4

from vision_rag.storage.metadata import Metadata, now


class Findings:
    def __init__(self, metadata: Metadata) -> None:
        self.meta = metadata

    def create(
        self, title: str, kind: str, content: dict[str, Any], saved: bool = False
    ) -> dict[str, Any]:
        value = json.dumps(content, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(value.encode()).hexdigest()
        key, timestamp = str(uuid4()), now()
        with self.meta.connection(True) as db:
            db.execute(
                "INSERT INTO findings VALUES (?,?,?,?,?,?,?,0,?,?)",
                (
                    key,
                    self.meta.workspace,
                    title,
                    kind,
                    "saved" if saved else "draft",
                    value,
                    digest,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(key)

    def get(self, key: str) -> dict[str, Any]:
        rows = self.meta.rows(
            "SELECT * FROM findings WHERE id=? AND workspace=?",
            (key, self.meta.workspace),
        )
        if not rows:
            raise KeyError(key)
        row = rows[0]
        return {
            **row,
            "content": json.loads(row["content"]),
            "reviewed": bool(row["reviewed"]),
        }

    def all(self) -> list[dict[str, Any]]:
        return self.meta.rows(
            "SELECT id,title,kind,state,content_hash,reviewed,created_at,updated_at "
            "FROM findings WHERE workspace=? AND state='saved' "
            "ORDER BY updated_at DESC,id",
            (self.meta.workspace,),
        )

    def update(
        self,
        key: str,
        title: str | None = None,
        reviewed: bool | None = None,
        save: bool = False,
    ) -> dict[str, Any]:
        self.get(key)
        with self.meta.connection(True) as db:
            if title is not None:
                db.execute(
                    "UPDATE findings SET title=? WHERE id=? AND workspace=?",
                    (title, key, self.meta.workspace),
                )
            if reviewed is not None:
                db.execute(
                    "UPDATE findings SET reviewed=? WHERE id=? AND workspace=?",
                    (int(reviewed), key, self.meta.workspace),
                )
            if save:
                db.execute(
                    "UPDATE findings SET state='saved' WHERE id=? AND workspace=?",
                    (key, self.meta.workspace),
                )
            db.execute(
                "UPDATE findings SET updated_at=? WHERE id=? AND workspace=?",
                (now(), key, self.meta.workspace),
            )
        return self.get(key)

    def delete(self, key: str) -> None:
        self.get(key)
        with self.meta.connection(True) as db:
            db.execute(
                "DELETE FROM findings WHERE id=? AND workspace=?",
                (key, self.meta.workspace),
            )

    def clear_drafts(self) -> None:
        with self.meta.connection(True) as db:
            db.execute(
                "DELETE FROM findings WHERE workspace=? AND state='draft'",
                (self.meta.workspace,),
            )
