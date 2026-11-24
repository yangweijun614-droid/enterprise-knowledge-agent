import argparse
from dataclasses import replace
from datetime import date
from importlib.resources import files
import json
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from enterprise_agent.agent import build_retriever
from enterprise_agent.api import create_app
from enterprise_agent.policy import load_clauses, visible_clauses
from enterprise_agent.settings import Settings


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(config: Settings) -> dict:
    benchmark = json.loads(files("enterprise_agent").joinpath(
        "data", "evaluation.json",
    ).read_text(encoding="utf-8"))
    policies = load_clauses()
    retriever = build_retriever(config, policies)
    recall_scores = {name: [] for name in ("bm25", "dense", "hybrid")}
    sessions = {}
    policy_rows = []
    approval_rows = []

    with TestClient(create_app(config)) as client:
        for case in benchmark["policy"]:
            permitted = visible_clauses(policies, case["role"], date.fromisoformat(case["as_of"]))
            permitted_text = {clause.id: clause.text for clause in permitted}
            gold = set(case["gold"])
            if not gold <= permitted_text.keys():
                raise ValueError(f"Gold labels are not visible on {case['id']}")
            rankings = {}
            for mode in recall_scores:
                retrieved = retriever.search(case["question"], permitted, mode=mode, limit=5)
                rankings[mode] = [clause.id for clause in retrieved]
                if gold:
                    recall_scores[mode].append(len(gold.intersection(rankings[mode])) / len(gold))
            actor = "bob" if case["role"] == "finance" else "alice"
            response = client.post(
                "/v1/chat", headers={"Authorization": f"Bearer demo-{actor}"},
                json={"message": case["question"], "as_of": case["as_of"]},
            )
            response.raise_for_status()
            body = response.json()
            citations = body["citations"]
            found = {item["clause_id"] for item in citations}
            fidelity = [item["quote"] == permitted_text.get(item["clause_id"]) for item in citations]
            policy_rows.append({
                **case, "rankings": rankings, "kind": body["kind"], "cited": sorted(found),
                "source_matches": sum(fidelity), "citations": len(citations),
                "supported_citations": len(gold & found),
                "correct": found == gold and all(fidelity)
                and body["kind"] == ("policy_answer" if gold else "no_evidence"),
            })

        for case in benchmark["approval"]:
            payload = {"message": case["message"]}
            if case.get("followup"):
                payload["session_id"] = sessions[case["followup"]]
            response = client.post(
                "/v1/chat", headers={"Authorization": f"Bearer demo-{case['actor']}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            sessions[case["id"]] = body["session_id"]
            tool, row = body["tool"], body["approval"]
            actual = tool["outcome"] if tool else None
            expected_id = case.get("approval_id")
            correct = (
                body["kind"] == case["kind"] and actual == case["tool"]
                and (tool is None or tool["name"] == "lookup_approval")
                and (row["id"] if row else None) == expected_id
            )
            approval_rows.append({
                **case, "actual_kind": body["kind"], "actual_tool": actual, "correct": correct,
            })

    refusals = [row for row in policy_rows if not row["gold"]]
    tool_calls = [row for row in approval_rows if row["actual_tool"] is not None]
    citation_count = sum(row["citations"] for row in policy_rows)
    return {
        "dataset": {"policy": len(policy_rows), "with_gold": len(policy_rows) - len(refusals),
                    "without_gold": len(refusals), "approval": len(approval_rows)},
        "backend": {
            "dense": f"Milvus / {config.embedding_model}" if config.milvus_uri else "local_tf_idf",
            "reranker": config.reranker_model or "local_topic_match",
            "evidence": config.vllm_model or "local_extract",
        },
        "metrics": {
            "macro_recall_at_5": {name: round(mean(scores), 4) for name, scores in recall_scores.items()},
            "policy_exact_match": ratio(sum(row["correct"] for row in policy_rows), len(policy_rows)),
            "no_answer_refusal": ratio(sum(row["correct"] for row in refusals), len(refusals)),
            "citation_source_fidelity": ratio(sum(row["source_matches"] for row in policy_rows), citation_count),
            "citation_gold_precision": ratio(sum(row["supported_citations"] for row in policy_rows), citation_count),
            "tool_success_rate": ratio(sum(row["correct"] for row in tool_calls), len(tool_calls)),
            "approval_scenario_accuracy": ratio(sum(row["correct"] for row in approval_rows), len(approval_rows)),
            "tool_calls": len(tool_calls),
        },
        "policy_cases": policy_rows,
        "approval_cases": approval_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the labeled Chinese policy and approval benchmark.")
    parser.add_argument("--json", action="store_true", help="include per-case ranks and expected results")
    parser.add_argument("--configured-models", action="store_true", help="use the model settings from the environment")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="enterprise-agent-eval-") as runtime:
        config = Settings.from_env() if args.configured_models else Settings()
        config = replace(config, demo=True, token_json=None, runtime_dir=Path(runtime))
        report = evaluate(config)
    if not args.json:
        report = {key: report[key] for key in ("dataset", "backend", "metrics")}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
