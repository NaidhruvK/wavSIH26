"""SQLite persistence layer for wavSIH26 / Raaya.

OWNED BY: Naidhruv.
Provides thread-safe persistence using Python's built-in sqlite3.
Stores runs and stage metrics with JSON serialization for nested structures.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import config

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    sha256 TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    envelope_verdict TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS stage_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    elapsed_ms REAL DEFAULT 0.0,
    reason TEXT,
    values_json TEXT DEFAULT '{}',
    hypotheses_json TEXT DEFAULT '[]',
    artifacts_json TEXT DEFAULT '{}',
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    UNIQUE(run_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_stage_results_run_id ON stage_results(run_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Provide a thread-safe connection with WAL mode and foreign keys enabled."""
    target_path = Path(db_path or config.db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(db_path: Path | str | None = None) -> None:
    """Initialize database tables and indexes."""
    with get_connection(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)


def create_run(
    run_id: str,
    filename: str,
    file_size: int = 0,
    sha256: str = "",
    status: str = "queued",
    envelope_verdict: str = "pending",
    created_at: Optional[str] = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Record a new analysis run."""
    ts = created_at or _now_iso()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO runs (run_id, filename, file_size, sha256, status, envelope_verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, filename, file_size, sha256, status, envelope_verdict, ts),
        )
    return get_run(run_id, db_path=db_path)  # type: ignore[return-value]


def update_run(
    run_id: str,
    status: Optional[str] = None,
    envelope_verdict: Optional[str] = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    error: Optional[str] = None,
    db_path: Path | str | None = None,
) -> Optional[dict[str, Any]]:
    """Update fields on an existing run record."""
    updates: list[str] = []
    params: list[Any] = []

    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if envelope_verdict is not None:
        updates.append("envelope_verdict = ?")
        params.append(envelope_verdict)
    if started_at is not None:
        updates.append("started_at = ?")
        params.append(started_at)
    if finished_at is not None:
        updates.append("finished_at = ?")
        params.append(finished_at)
    if error is not None:
        updates.append("error = ?")
        params.append(error)

    if not updates:
        return get_run(run_id, db_path=db_path)

    params.append(run_id)
    sql = f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?"
    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, tuple(params))
        if cursor.rowcount == 0:
            return None

    return get_run(run_id, db_path=db_path)


def get_run(run_id: str, db_path: Path | str | None = None) -> Optional[dict[str, Any]]:
    """Retrieve run record by run_id."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def _format_stage_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert SQLite row to clean dictionary with parsed JSON fields."""
    d = dict(row)
    d["values"] = json.loads(d.pop("values_json", "{}") or "{}")
    d["hypotheses"] = json.loads(d.pop("hypotheses_json", "[]") or "[]")
    d["artifacts"] = json.loads(d.pop("artifacts_json", "{}") or "{}")
    return d


def record_stage_result(
    run_id: str,
    stage: str,
    status: str,
    confidence: float,
    elapsed_ms: float = 0.0,
    reason: Optional[str] = None,
    values: Optional[dict[str, Any]] = None,
    hypotheses: Optional[list[Any]] = None,
    artifacts: Optional[dict[str, str]] = None,
    recorded_at: Optional[str] = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Store or update a stage execution result for a run."""
    ts = recorded_at or _now_iso()
    values_json = json.dumps(values or {})
    hypotheses_json = json.dumps(hypotheses or [])
    artifacts_json = json.dumps(artifacts or {})

    sql = """
    INSERT INTO stage_results (
        run_id, stage, status, confidence, elapsed_ms, reason,
        values_json, hypotheses_json, artifacts_json, recorded_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(run_id, stage) DO UPDATE SET
        status = excluded.status,
        confidence = excluded.confidence,
        elapsed_ms = excluded.elapsed_ms,
        reason = excluded.reason,
        values_json = excluded.values_json,
        hypotheses_json = excluded.hypotheses_json,
        artifacts_json = excluded.artifacts_json,
        recorded_at = excluded.recorded_at
    """
    with get_connection(db_path) as conn:
        conn.execute(
            sql,
            (
                run_id,
                stage,
                status,
                confidence,
                elapsed_ms,
                reason,
                values_json,
                hypotheses_json,
                artifacts_json,
                ts,
            ),
        )

    res = get_stage_result(run_id, stage, db_path=db_path)
    assert res is not None
    return res


def get_stage_result(
    run_id: str, stage: str, db_path: Path | str | None = None
) -> Optional[dict[str, Any]]:
    """Retrieve single stage result by run_id and stage name."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM stage_results WHERE run_id = ? AND stage = ?", (run_id, stage)
        ).fetchone()
        return _format_stage_dict(row) if row else None


def get_all_stage_results(
    run_id: str, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Retrieve all stage results associated with a run, ordered by execution id."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM stage_results WHERE run_id = ? ORDER BY id ASC", (run_id,)
        ).fetchall()
        return [_format_stage_dict(r) for r in rows]
