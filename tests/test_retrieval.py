from datetime import date

from enterprise_agent.policy import load_clauses, visible_clauses
from enterprise_agent.retrieval import LocalRetriever
from enterprise_agent.evidence import validate_quotes


def test_both_retrieval_paths_exclude_restricted_and_retired_clauses():
    clauses = load_clauses()
    visible = visible_clauses(clauses, "staff", date(2025, 7, 1))
    engine = LocalRetriever()
    for mode in ("bm25", "dense", "hybrid"):
        result = engine.search("财务内审抽样比例和酒店住宿标准", visible, mode=mode)
        ids = {clause.id for clause in result}
        assert "TRAVEL@2025#A1" in ids
        assert "TRAVEL@2024#A1" not in ids
        assert all(not item.startswith("AUDIT") for item in ids)


def test_validate_evidence_rejects_fabrication_and_unknown_ids():
    clause = next(item for item in load_clauses() if item.id == "TRAVEL@2025#A1")
    valid, *_ = validate_quotes(
        [
            {"id": "UNKNOWN", "quote": clause.text},
            {"id": clause.id, "quote": "所有住宿均可无限额报销"},
            {"id": clause.id, "quote": clause.text},
        ],
        [clause],
    )
    assert valid.clause_id == clause.id and valid.quote == clause.text
    assert len(validate_quotes([{"id": clause.id, "quote": "600元"}], [clause])) == 0
