import hashlib
import json

from enterprise_agent.policy import Clause
from enterprise_agent.settings import Settings


class MilvusVectorSearch:
    def __init__(self, settings: Settings, clauses: list[Clause], *, require_ready: bool = True):
        from pymilvus import MilvusClient
        from sentence_transformers import SentenceTransformer

        if not settings.milvus_uri or not settings.embedding_model:
            raise ValueError("Set AGENT_MILVUS_URI and AGENT_EMBEDDING_MODEL together")
        self.encoder = SentenceTransformer(settings.embedding_model, trust_remote_code=False)
        self.dimension = self.encoder.get_sentence_embedding_dimension()
        self.client = MilvusClient(
            uri=settings.milvus_uri, token=settings.milvus_token or "", timeout=15,
        )
        manifest = [[c.id, c.search_text, c.effective_from.isoformat(), c.roles] for c in clauses]
        fingerprint = json.dumps([settings.embedding_model, self.dimension, manifest],
                                 ensure_ascii=False).encode("utf-8")
        self.collection = "enterprise_policy_" + hashlib.sha256(fingerprint).hexdigest()[:16]
        if require_ready:
            self.assert_ready(clauses)

    def assert_ready(self, clauses: list[Clause]) -> None:
        if not self.client.has_collection(self.collection):
            raise RuntimeError("Milvus index is missing. Run python -m enterprise_agent.index first.")
        rows = self.client.get(self.collection, ids=[clause.id for clause in clauses], output_fields=["id"],
                               consistency_level="Strong", timeout=15)
        if {row["id"] for row in rows} != {clause.id for clause in clauses}:
            raise RuntimeError("Milvus index is incomplete. Run python -m enterprise_agent.index again.")

    def index(self, clauses: list[Clause]) -> None:
        from pymilvus import DataType

        if not self.client.has_collection(self.collection):
            schema = self.client.create_schema(auto_id=False)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
            indexes = self.client.prepare_index_params()
            indexes.add_index("vector", index_type="AUTOINDEX", metric_type="COSINE")
            self.client.create_collection(self.collection, schema=schema, index_params=indexes)
        vectors = self.encoder.encode([clause.search_text for clause in clauses], normalize_embeddings=True)
        self.client.upsert(self.collection, data=[
            {"id": clause.id, "vector": vector.tolist()}
            for clause, vector in zip(clauses, vectors, strict=True)
        ], timeout=30)
        self.client.load_collection(self.collection, timeout=30)
        self.assert_ready(clauses)

    def search(self, query: str, clauses: list[Clause], limit: int) -> list[Clause]:
        permitted = {clause.id: clause for clause in clauses}
        if not permitted:
            return []
        expression = "id in " + json.dumps(sorted(permitted), ensure_ascii=True)
        vector = self.encoder.encode([query], normalize_embeddings=True)[0].tolist()
        hits = self.client.search(
            collection_name=self.collection, data=[vector], anns_field="vector", filter=expression,
            limit=min(limit, len(permitted)), search_params={"metric_type": "COSINE", "params": {}},
            consistency_level="Strong", timeout=15,
        )
        return [permitted[hit["id"]] for hit in hits[0] if hit["id"] in permitted]
