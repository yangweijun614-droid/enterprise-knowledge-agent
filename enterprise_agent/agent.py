from dataclasses import dataclass, field
from datetime import date
import re
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel

from enterprise_agent.approval_mcp import APPROVAL_ID, TOOL_NAME
from enterprise_agent.evidence import Citation, QwenEvidenceSelector, extract_quotes, validate_quotes
from enterprise_agent.mcp_client import ApprovalClient
from enterprise_agent.policy import Clause, load_clauses, visible_clauses
from enterprise_agent.retrieval import BgeReranker, LocalRetriever
from enterprise_agent.settings import Settings
from enterprise_agent.storage import Approval


STATUS_HINT = re.compile(
    r"审批进度|审批状态|审批到哪|审批到哪一步|单据状态|单据进度|报销进度|查.{0,12}审批(?!流程|规则)"
)
POLICY_HINT = re.compile(r"标准|制度|流程|规定|凭证|材料|期限|比例|餐补|餐费|发票|打款|到账|报销款")


@dataclass(frozen=True)
class RequestContext:
    caller_token: str = field(repr=False)


class ToolEvent(BaseModel):
    name: str
    outcome: Literal["found", "unavailable", "error"]


class FlowState(TypedDict, total=False):
    question: str
    role: str
    as_of: date
    pending: bool
    approval_id: str
    kind: str
    answer: str
    citations: list[Citation]
    approval: Approval | None
    tool: ToolEvent | None


def build_retriever(settings: Settings, clauses: list[Clause]) -> LocalRetriever:
    dense = None
    if settings.milvus_uri or settings.embedding_model:
        from enterprise_agent.milvus_backend import MilvusVectorSearch
        dense = MilvusVectorSearch(settings, clauses)
    reranker = BgeReranker(settings.reranker_model) if settings.reranker_model else None
    return LocalRetriever(dense, reranker)


def build_flow(settings: Settings, approval_client: ApprovalClient):
    clauses = load_clauses()
    retriever = build_retriever(settings, clauses)
    if bool(settings.vllm_url) != bool(settings.vllm_model):
        raise ValueError("Set AGENT_VLLM_URL and AGENT_VLLM_MODEL together")
    model = (QwenEvidenceSelector(settings.vllm_url, settings.vllm_model, settings.vllm_key)
             if settings.vllm_url and settings.vllm_model else None)

    def route(state: FlowState):
        question = state["question"]
        numbers = dict.fromkeys(number.upper() for number in APPROVAL_ID.findall(question))
        if len(numbers) == 1:
            return {"approval_id": next(iter(numbers)), "kind": "lookup"}
        if len(numbers) > 1 or STATUS_HINT.search(question) or (
            state["pending"] and not POLICY_HINT.search(question)
        ):
            return {"kind": "clarify"}
        return {"kind": "retrieve"}

    def clarify(state: FlowState):
        return {"kind": "need_approval_id", "pending": True,
                "answer": "请提供一个报销单号，格式为 BX-1001。"}

    async def lookup(state: FlowState, runtime: Runtime[RequestContext]):
        result = await approval_client.lookup(state["approval_id"], runtime.context.caller_token)
        tool = ToolEvent(name=TOOL_NAME, outcome=result.outcome)
        if result.outcome == "found" and result.approval:
            row = result.approval
            return {"kind": "approval", "pending": False, "tool": tool, "approval": row,
                    "answer": f"{row.id} 当前状态为「{row.status}」。{row.step}。更新时间 {row.updated_at}。"}
        if result.outcome == "unavailable":
            return {"kind": "approval_unavailable", "pending": False, "tool": tool,
                    "answer": "无法查询该单据，请核对本人单号。"}
        return {"kind": "approval_service_error", "pending": True, "tool": tool,
                "answer": "审批查询服务暂时不可用，请稍后重试。"}

    def retrieve(state: FlowState):
        question = state["question"]
        permitted = visible_clauses(clauses, state["role"], state["as_of"])
        candidates = retriever.search(question, permitted, limit=5)
        items = model.select(question, candidates) if model else extract_quotes(question, candidates)
        citations = validate_quotes(items, candidates)
        if not citations:
            return {"kind": "no_evidence", "pending": False, "citations": [],
                    "answer": "当前可用的制度条款不足以回答这个问题。"}
        return {"kind": "policy_answer", "pending": False, "citations": citations,
                "answer": "\n".join(f"[{item.clause_id}] {item.quote}" for item in citations)}

    graph = StateGraph(FlowState, context_schema=RequestContext)
    graph.add_node("route", route)
    graph.add_node("clarify", clarify)
    graph.add_node("lookup", lookup)
    graph.add_node("retrieve", retrieve)
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", lambda state: state["kind"],
                                {"clarify": "clarify", "lookup": "lookup", "retrieve": "retrieve"})
    for node in ("clarify", "lookup", "retrieve"):
        graph.add_edge(node, END)
    return graph.compile()
