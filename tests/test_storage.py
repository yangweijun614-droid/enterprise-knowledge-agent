from datetime import date

import pytest

from enterprise_agent.milvus_backend import MilvusVectorSearch
from enterprise_agent.policy import load_clauses, visible_clauses
from enterprise_agent.storage import SessionConflict, SessionStore


def test_stale_session_revision_cannot_replace_current_pending_state(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    first = store.open("test", "alice")
    second = store.open("test", "alice")
    store.finish("test", "alice", first.revision, True)
    with pytest.raises(SessionConflict):
        store.finish("test", "alice", second.revision, False)
    assert store.open("test", "alice").pending is True


def test_milvus_request_filters_ids_and_discards_out_of_scope_hit():
    visible = visible_clauses(load_clauses(), "staff", date(2025, 7, 1))

    class Vector:
        def tolist(self):
            return [0.2, 0.8]

    class Encoder:
        def encode(self, texts, **kwargs):
            return [Vector()]

    class Database:
        def search(self, **kwargs):
            expression = kwargs["filter"]
            assert "TRAVEL@2025#A1" in expression
            assert "TRAVEL@2024#A1" not in expression
            assert "AUDIT" not in expression
            return [[{"id": "AUDIT@2025#C1"}, {"id": "TRAVEL@2025#A1"}]]

    search = MilvusVectorSearch.__new__(MilvusVectorSearch)
    search.client, search.encoder, search.collection = Database(), Encoder(), "test"
    hits = search.search("酒店", visible, 5)
    assert [item.id for item in hits] == ["TRAVEL@2025#A1"]
