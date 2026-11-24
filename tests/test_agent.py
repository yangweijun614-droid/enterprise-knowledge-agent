from pathlib import Path

from fastapi.testclient import TestClient

from enterprise_agent.api import create_app
from enterprise_agent.settings import Settings


ALICE = {"Authorization": "Bearer demo-alice"}
BOB = {"Authorization": "Bearer demo-bob"}


def ask(client, message, auth=ALICE, session_id=None):
    payload = {"message": message}
    if session_id:
        payload["session_id"] = session_id
    return client.post("/v1/chat", headers=auth, json=payload)


def test_policy_version_and_citation(tmp_path):
    with TestClient(create_app(Settings(demo=True, runtime_dir=tmp_path))) as client:
        text = "国内出差的一线城市酒店住宿标准是多少？"
        current = ask(client, text).json()
        earlier = ask(client, "截至2024-06-01，" + text).json()
        assert current["kind"] == earlier["kind"] == "policy_answer"
        assert current["citations"][0]["clause_id"] == "TRAVEL@2025#A1"
        assert "600元" in current["answer"]
        assert earlier["citations"][0]["clause_id"] == "TRAVEL@2024#A1"
        assert "500元" in earlier["answer"]
        assert current["citations"][0]["quote"] in current["answer"]


def test_acl_and_unknown_answer(tmp_path):
    with TestClient(create_app(Settings(demo=True, runtime_dir=tmp_path))) as client:
        question = "财务内审抽样比例是多少？"
        denied = ask(client, question).json()
        allowed = ask(client, question, BOB).json()
        assert denied["kind"] == "no_evidence" and not denied["citations"]
        assert allowed["kind"] == "policy_answer"
        assert "10%" in allowed["answer"]
        unknown = ask(client, "宠物住院费用可以报销吗？").json()
        assert unknown["kind"] == "no_evidence"


def test_mcp_followup_survives_restart_and_is_scoped_to_owner(tmp_path):
    settings = Settings(demo=True, runtime_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        first = ask(client, "查一下我的报销审批进度").json()
        assert first["kind"] == "need_approval_id"
        assert first["tool"] is None
        sid = first["session_id"]

    with TestClient(create_app(settings)) as client:
        assert ask(client, "BX-1001", BOB, sid).status_code == 404
        own = ask(client, "是 BX-1001", session_id=sid).json()
        assert own["kind"] == "approval"
        assert own["approval"]["status"] == "财务复核中"
        assert own["tool"] == {"name": "lookup_approval", "outcome": "found"}
        foreign = ask(client, "帮我查 BX-2002").json()
        absent = ask(client, "帮我查 BX-9999").json()
        assert foreign["kind"] == absent["kind"] == "approval_unavailable"
        assert foreign["approval"] is None
        assert foreign["answer"] == absent["answer"]
        assert foreign["tool"] == {"name": "lookup_approval", "outcome": "unavailable"}


def test_auth_and_explicit_demo_mode(tmp_path):
    with TestClient(create_app(Settings(demo=True, runtime_dir=tmp_path))) as client:
        assert ask(client, "酒店标准", {}).status_code == 401
        assert ask(client, "酒店标准", {"Authorization": "Bearer invalid"}).status_code == 401
    try:
        create_app(Settings(demo=False, runtime_dir=Path(tmp_path)))
    except ValueError as error:
        assert "token" in str(error).lower()
    else:
        raise AssertionError("Missing authentication configuration was accepted")
