from dataclasses import dataclass
from datetime import date
from importlib.resources import files
import json


@dataclass(frozen=True)
class Clause:
    id: str
    policy_id: str
    title: str
    heading: str
    version: str
    effective_from: date
    roles: tuple[str, ...]
    text: str
    topics: tuple[str, ...]

    @property
    def search_text(self) -> str:
        return " ".join((self.heading, self.text, *self.topics))


def load_clauses() -> list[Clause]:
    raw = files("enterprise_agent").joinpath("data", "policies.json").read_text(encoding="utf-8")
    clauses = []
    versions = set()
    ids = set()
    for document in json.loads(raw):
        policy_id = document["policy_id"]
        version = document["version"]
        effective_from = date.fromisoformat(document["effective_from"])
        key = (policy_id, effective_from)
        if key in versions:
            raise ValueError(f"Duplicate policy effective date: {key}")
        versions.add(key)
        roles = tuple(document["roles"])
        if not roles or not set(roles) <= {"staff", "finance"}:
            raise ValueError(f"Invalid policy roles for {policy_id}")
        for article in document["clauses"]:
            clause_id = f"{policy_id}@{version}#{article['id']}"
            if clause_id in ids or not article["text"].strip() or not article["topics"]:
                raise ValueError(f"Invalid or duplicate clause: {clause_id}")
            ids.add(clause_id)
            clauses.append(Clause(
                clause_id, policy_id, document["title"], article["heading"], version,
                effective_from, roles, article["text"], tuple(article["topics"]),
            ))
    return clauses


def visible_clauses(clauses: list[Clause], role: str, as_of: date) -> list[Clause]:
    latest = {}
    for clause in clauses:
        if clause.effective_from <= as_of:
            latest[clause.policy_id] = max(
                latest.get(clause.policy_id, date.min), clause.effective_from,
            )
    return [
        clause for clause in clauses
        if latest.get(clause.policy_id) == clause.effective_from and role in clause.roles
    ]
