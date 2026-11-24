from enterprise_agent.milvus_backend import MilvusVectorSearch
from enterprise_agent.policy import load_clauses
from enterprise_agent.settings import Settings


def main() -> None:
    clauses = load_clauses()
    index = MilvusVectorSearch(Settings.from_env(), clauses, require_ready=False)
    index.index(clauses)
    print(f"Verified {len(clauses)} indexed clauses in {index.collection}")


if __name__ == "__main__":
    main()
