from collections import Counter, defaultdict
from math import log, sqrt
import re
from typing import Protocol

from enterprise_agent.policy import Clause


def normalize(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())


def tokens(text: str) -> list[str]:
    terms = []
    for word in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.casefold()):
        if "\u4e00" <= word[0] <= "\u9fff" and len(word) > 1:
            terms.extend(word[index:index + 2] for index in range(len(word) - 1))
        else:
            terms.append(word)
    return terms


def bm25_scores(query: list[str], docs: list[Counter]) -> list[float]:
    total = len(docs)
    avg_length = sum(sum(doc.values()) for doc in docs) / total or 1.0
    weighted_terms = {}
    for term in set(query):
        freq = sum(term in doc for doc in docs)
        weighted_terms[term] = log(1 + (total - freq + 0.5) / (freq + 0.5))
    scores = []
    for doc in docs:
        length_weight = 1.5 * (0.25 + 0.75 * sum(doc.values()) / avg_length)
        scores.append(sum(
            idf * (doc[term] * 2.5) / (doc[term] + length_weight)
            for term, idf in weighted_terms.items() if term in doc
        ))
    return scores


class DenseSearch(Protocol):
    def search(self, query: str, clauses: list[Clause], limit: int) -> list[Clause]: ...


def ranked(clauses: list[Clause], scores: list[float], limit: int) -> list[Clause]:
    scored = sorted(zip(clauses, scores, strict=True), key=lambda item: (-item[1], item[0].id))
    return [clause for clause, score in scored[:limit] if score > 0]


class LocalVectorSearch:
    """An inspectable, offline TF–IDF cosine baseline."""

    def search(self, query: str, clauses: list[Clause], limit: int) -> list[Clause]:
        vectors = [Counter(tokens(clause.search_text)) for clause in clauses]
        frequencies = Counter(term for vector in vectors for term in vector)
        idf = {
            term: 1 + log((1 + len(vectors)) / (1 + count))
            for term, count in frequencies.items()
        }
        query_vector = {term: count * idf.get(term, 1.0) for term, count in Counter(tokens(query)).items()}
        query_norm = sqrt(sum(value ** 2 for value in query_vector.values())) or 1.0
        scores = []
        for vector in vectors:
            weighted = {term: count * idf[term] for term, count in vector.items()}
            norm = sqrt(sum(value ** 2 for value in weighted.values())) or 1.0
            scores.append(sum(value * weighted.get(term, 0) for term, value in query_vector.items())
                          / (norm * query_norm))
        return ranked(clauses, scores, limit)


class BgeReranker:
    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name, trust_remote_code=False)

    def scores(self, query: str, clauses: list[Clause]) -> list[float]:
        return list(map(float, self.model.predict([(query, item.search_text) for item in clauses])))


def topic_match(query: str, clause: Clause) -> int:
    return max((len(term) for topic in clause.topics
                if (term := normalize(topic)) and term in query), default=0)


class LocalRetriever:
    def __init__(self, dense: DenseSearch | None = None, reranker: BgeReranker | None = None):
        self.dense = dense or LocalVectorSearch()
        self.reranker = reranker

    def search(self, query: str, clauses: list[Clause], *, mode: str = "hybrid",
               limit: int = 5) -> list[Clause]:
        if mode not in {"bm25", "dense", "hybrid"} or limit < 1:
            raise ValueError("Invalid retrieval mode or limit")
        if not clauses or not tokens(query):
            return []
        if mode == "dense":
            return self.dense.search(query, clauses, limit)
        candidate_limit = max(10, limit * 2) if mode == "hybrid" else limit
        lexical = ranked(clauses, bm25_scores(tokens(query), [
            Counter(tokens(clause.search_text)) for clause in clauses
        ]), candidate_limit)
        if mode == "bm25":
            return lexical
        dense = self.dense.search(query, clauses, candidate_limit)
        fused = defaultdict(float)
        for result in (lexical, dense):
            for position, clause in enumerate(result, start=1):
                fused[clause] += 1.0 / (60 + position)
        candidates = sorted(fused, key=lambda item: (-fused[item], item.id))[:candidate_limit]
        if not candidates:
            return []
        if self.reranker:
            scores = dict(zip(candidates, self.reranker.scores(query, candidates), strict=True))
            return sorted(candidates, key=lambda item: (-scores[item], -fused[item], item.id))[:limit]
        normalized = normalize(query)
        return sorted(candidates, key=lambda item: (-topic_match(normalized, item),
                                                     -fused[item], item.id))[:limit]
