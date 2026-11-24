from contextlib import closing
from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path
import sqlite3

from pydantic import BaseModel


class Approval(BaseModel):
    id: str
    status: str
    step: str
    updated_at: str


class SessionNotFound(Exception):
    pass


class SessionConflict(Exception):
    pass


@dataclass(frozen=True)
class Session:
    revision: int
    pending: bool


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0
                )"""
            )

    def open(self, session_id: str, owner: str) -> Session:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO sessions (id, owner) VALUES (?, ?)", (session_id, owner))
            row = db.execute(
                "SELECT revision, pending FROM sessions WHERE id = ? AND owner = ?", (session_id, owner),
            ).fetchone()
        if row is None:
            raise SessionNotFound
        return Session(row[0], bool(row[1]))

    def finish(self, session_id: str, owner: str, revision: int, pending: bool) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute(
                """UPDATE sessions SET revision = revision + 1, pending = ?
                   WHERE id = ? AND owner = ? AND revision = ?""",
                (int(pending), session_id, owner, revision),
            )
            if cursor.rowcount != 1:
                raise SessionConflict


class ApprovalStore:
    def __init__(self, path: Path):
        self.path = path

    def seed_example_data(self) -> None:
        raw = files("enterprise_agent").joinpath("data", "approvals.json").read_text(encoding="utf-8")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
                    step TEXT NOT NULL, updated_at TEXT NOT NULL
                )"""
            )
            db.executemany(
                """INSERT OR IGNORE INTO approvals (id, owner, status, step, updated_at)
                   VALUES (:id, :owner, :status, :step, :updated_at)""",
                json.loads(raw),
            )

    def get_for_owner(self, approval_id: str, owner: str) -> Approval | None:
        uri = self.path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT id, status, step, updated_at FROM approvals WHERE id = ? AND owner = ?",
                (approval_id, owner),
            ).fetchone()
        return Approval.model_validate(dict(row)) if row is not None else None
