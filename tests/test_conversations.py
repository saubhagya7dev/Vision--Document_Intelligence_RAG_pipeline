import pytest

from vision_rag.storage.conversations import Conversations
from vision_rag.storage.metadata import Conflict, Metadata


def test_conversations_survive_restart_and_enforce_workspace_scope(tmp_path):
    path = tmp_path / "metadata.sqlite"
    store = Conversations(Metadata(path, "first"))
    conversation = store.create("Report review", ["document-one"])
    turn = store.start(conversation["id"], {"query": "What is revenue?"})
    store.update(conversation["id"], {"document_ids": ["document-two"]})
    assert store.message(turn["id"])["request"]["document_ids"] == ["document-one"]
    with pytest.raises(Conflict):
        store.start(conversation["id"], {"query": "Another question"})
    other = Conversations(Metadata(path, "second"))
    for action in (other.get, other.delete, other.message, other.cancel):
        with pytest.raises(KeyError):
            action(
                turn["id"]
                if action in (other.message, other.cancel)
                else conversation["id"]
            )
    restarted = Conversations(Metadata(path, "first"))
    restarted.recover()
    assert restarted.message(turn["id"])["state"] == "interrupted"
    assert [e["sequence"] for e in restarted.events(turn["id"])] == [1, 2]
    next_turn = restarted.start(conversation["id"], {"query": "What about profit?"})
    restarted.cancel(next_turn["id"])
    restarted.finish(next_turn["id"], "completed", {"answer": "must not publish"})
    assert restarted.message(next_turn["id"])["result"] is None
    restarted.delete(conversation["id"])
    assert not restarted.all()
    assert not restarted.meta.rows("SELECT * FROM message_events")


def test_conversation_viewer_and_final_answer_publish_atomically(tmp_path):
    store = Conversations(Metadata(tmp_path / "metadata.sqlite"))
    conversation = store.create("Review", None)
    store.update(conversation["id"], {"viewer": {"page": 2, "zoom": 1.5}})
    turn = store.start(conversation["id"], {"query": "Question"})
    store.event(turn["id"], "answer-delta", {"text": "draft"})
    store.finish(turn["id"], "completed", {"answer": "validated", "sources": []})
    store.event(turn["id"], "answer-delta", {"text": "too late"})
    assert store.events(turn["id"])[-1]["type"] == "final-answer"
    assert store.get(conversation["id"])["viewer"]["page"] == 2
    store.clear()
    assert not store.meta.rows("SELECT * FROM messages")
