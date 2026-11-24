from contextlib import asynccontextmanager
from datetime import date
import re
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langsmith import tracing_context
from pydantic import BaseModel, Field, StringConstraints

from enterprise_agent.agent import RequestContext, ToolEvent, build_flow
from enterprise_agent.evidence import Citation, ModelUnavailable
from enterprise_agent.mcp_client import open_approval_client
from enterprise_agent.settings import Auth, Settings, credentials
from enterprise_agent.storage import Approval, ApprovalStore, SessionConflict, SessionNotFound, SessionStore


Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
SessionId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


class ChatRequest(BaseModel):
    message: Message
    session_id: SessionId | None = None
    as_of: date | None = None


class ChatResponse(BaseModel):
    session_id: str
    as_of: date
    kind: Literal["need_approval_id", "approval", "approval_unavailable",
                  "approval_service_error", "policy_answer", "no_evidence"]
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    approval: Approval | None = None
    tool: ToolEvent | None = None


def effective_date(request: ChatRequest) -> date:
    if request.as_of is not None:
        return request.as_of
    match = re.search(r"(?:截至|以|按)\s*(\d{4}-\d{2}-\d{2})(?![0-9])", request.message)
    if match is None:
        return date.today()
    try:
        return date.fromisoformat(match.group(1))
    except ValueError as error:
        raise HTTPException(422, "制度日期无效，请使用 YYYY-MM-DD。") from error


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    token_config = credentials(config)
    auth = Auth(token_config)
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.runtime_dir.mkdir(parents=True, exist_ok=True)
        approvals = ApprovalStore(config.runtime_dir / "approvals.sqlite3")
        approvals.seed_example_data()
        app.state.sessions = SessionStore(config.runtime_dir / "sessions.sqlite3")
        async with open_approval_client(approvals.path, token_config) as approval_client:
            app.state.graph = build_flow(config, approval_client)
            yield

    app = FastAPI(title="企业知识库与审批查询 Agent", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest,
                   credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        principal = auth.resolve(credential.credentials) if credential else None
        if principal is None:
            raise HTTPException(401, "需要有效的 Bearer token。", headers={"WWW-Authenticate": "Bearer"})
        as_of = effective_date(request)
        sid = request.session_id or uuid4().hex
        sessions: SessionStore = app.state.sessions
        try:
            current = sessions.open(sid, principal.user_id)
            with tracing_context(enabled=False):
                result = await app.state.graph.ainvoke(
                    {"question": request.message, "role": principal.role, "as_of": as_of,
                     "pending": current.pending},
                    context=RequestContext(credential.credentials),
                )
            sessions.finish(sid, principal.user_id, current.revision, result["pending"])
        except SessionNotFound as error:
            raise HTTPException(404, "会话不可用。") from error
        except SessionConflict as error:
            raise HTTPException(409, "同一会话有并发请求，请重试。") from error
        except ModelUnavailable as error:
            raise HTTPException(503, "模型服务暂时不可用。") from error
        return ChatResponse(
            session_id=sid, as_of=as_of, kind=result["kind"], answer=result["answer"],
            citations=result.get("citations", []), approval=result.get("approval"), tool=result.get("tool"),
        )

    return app
