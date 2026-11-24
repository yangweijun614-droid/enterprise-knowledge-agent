import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str


@dataclass(frozen=True)
class Settings:
    demo: bool = False
    runtime_dir: Path = Path(".runtime")
    token_json: str | None = field(default=None, repr=False)
    milvus_uri: str | None = None
    milvus_token: str | None = field(default=None, repr=False)
    embedding_model: str | None = None
    reranker_model: str | None = None
    vllm_url: str | None = None
    vllm_model: str | None = None
    vllm_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls):
        return cls(
            demo=os.getenv("AGENT_DEMO") == "1",
            runtime_dir=Path(os.getenv("AGENT_RUNTIME_DIR", ".runtime")),
            token_json=os.getenv("AGENT_TOKEN_JSON"),
            milvus_uri=os.getenv("AGENT_MILVUS_URI"),
            milvus_token=os.getenv("AGENT_MILVUS_TOKEN"),
            embedding_model=os.getenv("AGENT_EMBEDDING_MODEL"),
            reranker_model=os.getenv("AGENT_RERANKER_MODEL"),
            vllm_url=os.getenv("AGENT_VLLM_URL"),
            vllm_model=os.getenv("AGENT_VLLM_MODEL"),
            vllm_key=os.getenv("AGENT_VLLM_KEY"),
        )


class Auth:
    def __init__(self, config: str):
        records = json.loads(config)
        if not isinstance(records, dict) or not records:
            raise ValueError("token config must be a non-empty JSON object")
        self.records = []
        for token, entry in records.items():
            if (not token or not isinstance(entry, dict)
                    or not isinstance(entry.get("user_id"), str) or not entry["user_id"]
                    or entry.get("role") not in ("staff", "finance")):
                raise ValueError("Invalid token entry")
            self.records.append((
                self.digest(token), Principal(entry["user_id"], entry["role"]),
            ))

    @staticmethod
    def digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    def resolve(self, token: str) -> Principal | None:
        digest = self.digest(token)
        return next((p for key, p in self.records if hmac.compare_digest(digest, key)), None)


def credentials(settings: Settings) -> str:
    if settings.token_json:
        return settings.token_json
    if settings.demo:
        return json.dumps({
            "demo-alice": {"user_id": "alice", "role": "staff"},
            "demo-bob": {"user_id": "bob", "role": "finance"},
        })
    raise ValueError("Configure AGENT_TOKEN_JSON or explicitly enable demo tokens with AGENT_DEMO=1")
