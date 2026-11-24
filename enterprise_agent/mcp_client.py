from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
import sys

from anyio import BrokenResourceError, ClosedResourceError, EndOfStream
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from enterprise_agent.approval_mcp import ApprovalLookup, TOOL_NAME


class ApprovalClient:
    def __init__(self, session: ClientSession):
        self.session = session

    async def lookup(self, approval_id: str, caller_token: str) -> ApprovalLookup:
        try:
            result = await self.session.call_tool(
                TOOL_NAME, arguments={"approval_id": approval_id, "caller_token": caller_token},
            )
            if result.isError:
                return ApprovalLookup(outcome="error")
            data = ApprovalLookup.model_validate(result.structuredContent)
            if (data.outcome == "found") != (data.approval is not None):
                return ApprovalLookup(outcome="error")
            if data.approval and data.approval.id != approval_id:
                return ApprovalLookup(outcome="error")
            return data
        except (McpError, TimeoutError, ValidationError, OSError,
                BrokenResourceError, ClosedResourceError, EndOfStream):
            return ApprovalLookup(outcome="error")


@asynccontextmanager
async def open_approval_client(db: Path, token_config: str):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "enterprise_agent.approval_mcp"],
        env={
            "AGENT_MCP_DB": str(db.resolve()),
            "AGENT_MCP_TOKEN_JSON": token_config,
            "PYTHONUTF8": "1",
        },
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=8)) as session:
            await session.initialize()
            tools = await session.list_tools()
            if {tool.name for tool in tools.tools} != {TOOL_NAME}:
                raise RuntimeError("Unexpected approval service tools")
            yield ApprovalClient(session)
