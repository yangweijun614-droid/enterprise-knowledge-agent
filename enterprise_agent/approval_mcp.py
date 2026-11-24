from pathlib import Path
from typing import Literal
import os
import re

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from enterprise_agent.settings import Auth
from enterprise_agent.storage import Approval, ApprovalStore


TOOL_NAME = "lookup_approval"
APPROVAL_ID = re.compile(r"(?<![A-Z0-9-])BX-[0-9]{4}(?![A-Z0-9-])", re.IGNORECASE | re.ASCII)


class ApprovalLookup(BaseModel):
    outcome: Literal["found", "unavailable", "error"]
    approval: Approval | None = None


def build_server(store: ApprovalStore, auth: Auth) -> FastMCP:
    server = FastMCP("enterprise-approval-readonly")

    @server.tool(name=TOOL_NAME)
    def lookup_approval(approval_id: str, caller_token: str) -> ApprovalLookup:
        """Return the approval only if the authenticated caller owns it."""
        principal = auth.resolve(caller_token)
        if principal is None or not APPROVAL_ID.fullmatch(approval_id):
            return ApprovalLookup(outcome="unavailable")
        approval = store.get_for_owner(approval_id.upper(), principal.user_id)
        if approval is None:
            return ApprovalLookup(outcome="unavailable")
        return ApprovalLookup(outcome="found", approval=approval)

    return server


def main() -> None:
    store = ApprovalStore(Path(os.environ["AGENT_MCP_DB"]))
    auth = Auth(os.environ["AGENT_MCP_TOKEN_JSON"])
    build_server(store, auth).run(transport="stdio")


if __name__ == "__main__":
    main()
