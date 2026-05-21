from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api_db import db_cursor


TRACEABILITY_DDL = """
IF NOT EXISTS (
    SELECT 1
    FROM sys.tables
    WHERE name = 'traceability_matrix' AND schema_id = SCHEMA_ID('dbo')
)
BEGIN
    CREATE TABLE dbo.traceability_matrix (
        id                        UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
        user_id                   UNIQUEIDENTIFIER NOT NULL,
        conversation_id           NVARCHAR(100)    NULL,
        trace_type                NVARCHAR(30)     NOT NULL,
        question                  NVARCHAR(MAX)    NULL,
        answer                    NVARCHAR(MAX)    NULL,
        intent                    NVARCHAR(100)    NULL,
        target_docs_json          NVARCHAR(MAX)    NULL,
        retrieved_sources_json    NVARCHAR(MAX)    NULL,
        generation_sources_json   NVARCHAR(MAX)    NULL,
        regulatory_session_id     NVARCHAR(100)    NULL,
        regulatory_step           NVARCHAR(100)    NULL,
        download_name             NVARCHAR(255)    NULL,
        result                    NVARCHAR(20)     NULL,
        error_type                NVARCHAR(10)     NULL,
        severity                  NVARCHAR(20)     NULL,
        reviewer_notes            NVARCHAR(MAX)    NULL,
        created_at                DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at                DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_traceability_type CHECK (trace_type IN ('chat','regulatory_analysis','regulatory_document')),
        CONSTRAINT CK_traceability_result CHECK (result IS NULL OR result IN ('OK','PARCIAL','NOK')),
        CONSTRAINT CK_traceability_error_type CHECK (error_type IS NULL OR error_type IN ('E1','E2','E3','E4','E5','E6','E7')),
        CONSTRAINT CK_traceability_severity CHECK (severity IS NULL OR severity IN ('baixa','média','alta'))
    );

    CREATE INDEX IX_traceability_user_created
        ON dbo.traceability_matrix(user_id, created_at DESC);

    CREATE INDEX IX_traceability_conversation
        ON dbo.traceability_matrix(conversation_id, created_at DESC);
END
"""


def init_traceability_schema() -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(TRACEABILITY_DDL)


def _json_dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: Optional[str]) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


def log_chat_trace(
    *,
    user_id: str,
    conversation_id: Optional[str],
    question: str,
    answer: str,
    intent: Optional[str],
    target_docs: Optional[List[str]],
    retrieved_sources: Optional[List[Dict[str, Any]]],
    generation_sources: Optional[List[Dict[str, Any]]],
) -> str:
    trace_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dbo.traceability_matrix (
                id, user_id, conversation_id, trace_type,
                question, answer, intent,
                target_docs_json, retrieved_sources_json, generation_sources_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 'chat', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trace_id,
            user_id,
            conversation_id,
            question,
            answer,
            intent,
            _json_dump(target_docs or []),
            _json_dump(retrieved_sources or []),
            _json_dump(generation_sources or []),
            now,
            now,
        )

    return trace_id


def log_regulatory_analysis_trace(
    *,
    user_id: str,
    conversation_id: Optional[str],
    question: str,
    assistant_text: str,
    session_id: str,
    step: str,
    analysis: Optional[Dict[str, Any]],
    target_docs: Optional[List[str]] = None,
) -> str:
    trace_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dbo.traceability_matrix (
                id, user_id, conversation_id, trace_type,
                question, answer, intent,
                target_docs_json, retrieved_sources_json, generation_sources_json,
                regulatory_session_id, regulatory_step,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 'regulatory_analysis', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trace_id,
            user_id,
            conversation_id,
            question,
            assistant_text,
            None,
            _json_dump(target_docs or []),
            _json_dump([]),
            _json_dump(analysis or {}),
            session_id,
            step,
            now,
            now,
        )

    return trace_id


def log_regulatory_document_trace(
    *,
    user_id: str,
    conversation_id: Optional[str],
    session_id: str,
    step: str,
    assistant_text: str,
    download_name: Optional[str],
    filled_fields: Optional[List[Dict[str, Any]]],
    flagged_fields: Optional[List[Dict[str, Any]]],
) -> str:
    trace_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dbo.traceability_matrix (
                id, user_id, conversation_id, trace_type,
                question, answer, intent,
                target_docs_json, retrieved_sources_json, generation_sources_json,
                regulatory_session_id, regulatory_step, download_name,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 'regulatory_document', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            trace_id,
            user_id,
            conversation_id,
            None,
            assistant_text,
            None,
            _json_dump(["MDR", "AI_ACT"]),
            _json_dump(filled_fields or []),
            _json_dump(flagged_fields or []),
            session_id,
            step,
            download_name,
            now,
            now,
        )

    return trace_id


def list_traceability_entries(
    *,
    user_id: str,
    limit: int = 100,
    conversation_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        if conversation_id:
            cur.execute(
                """
                SELECT TOP (?) id, user_id, conversation_id, trace_type,
                    question, answer, intent,
                    target_docs_json, retrieved_sources_json, generation_sources_json,
                    regulatory_session_id, regulatory_step, download_name,
                    result, error_type, severity, reviewer_notes,
                    created_at, updated_at
                FROM dbo.traceability_matrix
                WHERE user_id = ?
                AND conversation_id = ?
            ORDER BY created_at DESC
                """,
                limit,
                user_id,
                conversation_id,
            )
        else:
            cur.execute(
                """
                SELECT TOP (?) id, user_id, conversation_id, trace_type,
                    question, answer, intent,
                    target_docs_json, retrieved_sources_json, generation_sources_json,
                    regulatory_session_id, regulatory_step, download_name,
                    result, error_type, severity, reviewer_notes,
                    created_at, updated_at
                FROM dbo.traceability_matrix
                WHERE user_id = ?
            ORDER BY created_at DESC
                """,
                limit,
                user_id,
            )
        rows = cur.fetchall()

    result = []
    for r in rows:
        result.append(
            {
                "id": str(r[0]),
                "user_id": str(r[1]),
                "conversation_id": r[2],
                "trace_type": r[3],
                "question": r[4],
                "answer": r[5],
                "intent": r[6],
                "target_docs": _json_load(r[7]) or [],
                "retrieved_sources": _json_load(r[8]) or [],
                "generation_sources": _json_load(r[9]) or [],
                "regulatory_session_id": r[10],
                "regulatory_step": r[11],
                "download_name": r[12],
                "result": r[13],
                "error_type": r[14],
                "severity": r[15],
                "reviewer_notes": r[16],
                "created_at": _iso(r[17]),
                "updated_at": _iso(r[18]),
            }
        )
    return result


def list_all_traceability_entries(
    *,
    limit: int = 200,
    trace_type: Optional[str] = None,
    result: Optional[str] = None,
    severity: Optional[str] = None,
    error_type: Optional[str] = None,
    only_pending: bool = False,
) -> List[Dict[str, Any]]:
    """Variante 'admin' que NÃO filtra por user_id. Suporta filtros por
    trace_type/result/severity/error_type/only_pending (result IS NULL)."""
    where: List[str] = ["1=1"]
    params: List[Any] = []
    if trace_type:
        where.append("trace_type = ?")
        params.append(trace_type)
    if only_pending:
        where.append("result IS NULL")
    elif result:
        where.append("result = ?")
        params.append(result)
    if severity:
        where.append("severity = ?")
        params.append(severity)
    if error_type:
        where.append("error_type = ?")
        params.append(error_type)

    sql = f"""
        SELECT TOP (?) id, user_id, conversation_id, trace_type,
            question, answer, intent,
            target_docs_json, retrieved_sources_json, generation_sources_json,
            regulatory_session_id, regulatory_step, download_name,
            result, error_type, severity, reviewer_notes,
            created_at, updated_at
        FROM dbo.traceability_matrix
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
    """

    with db_cursor() as cur:
        cur.execute(sql, limit, *params)
        rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": str(r[0]),
                "user_id": str(r[1]),
                "conversation_id": r[2],
                "trace_type": r[3],
                "question": r[4],
                "answer": r[5],
                "intent": r[6],
                "target_docs": _json_load(r[7]) or [],
                "retrieved_sources": _json_load(r[8]) or [],
                "generation_sources": _json_load(r[9]) or [],
                "regulatory_session_id": r[10],
                "regulatory_step": r[11],
                "download_name": r[12],
                "result": r[13],
                "error_type": r[14],
                "severity": r[15],
                "reviewer_notes": r[16],
                "created_at": _iso(r[17]),
                "updated_at": _iso(r[18]),
            }
        )
    return out


def update_traceability_review_admin(
    *,
    trace_id: str,
    reviewer_id: str,
    result: Optional[str],
    error_type: Optional[str],
    severity: Optional[str],
    reviewer_notes: Optional[str],
) -> Dict[str, Any]:
    """Variante 'admin/specialist' — não filtra por user_id do criador.
    Pode ser usada por qualquer reviewer (admin ou specialist) para marcar
    uma entrada como revista, independentemente de quem a criou.

    `reviewer_id` é guardado em `reviewer_notes` como prefixo se as notas
    não estiverem vazias — para mantermos pista de quem reviu (sem
    quebrar o schema atual).
    """
    now = datetime.now(timezone.utc)

    # Tag de reviewer SEMPRE presente nas notas — independentemente de o
    # reviewer ter escrito notas ou não. É crucial para o SpecialistDashboard
    # /SpecialistHistory conseguirem filtrar "as minhas revisões".
    tag = f"[reviewer:{reviewer_id[:8]}]"
    if reviewer_notes:
        if tag in reviewer_notes:
            notes_with_reviewer = reviewer_notes
        else:
            notes_with_reviewer = f"{tag} {reviewer_notes}".strip()
    else:
        notes_with_reviewer = tag

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE dbo.traceability_matrix
               SET result = ?,
                   error_type = ?,
                   severity = ?,
                   reviewer_notes = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            result,
            error_type,
            severity,
            notes_with_reviewer,
            now,
            trace_id,
        )
        if cur.rowcount == 0:
            raise ValueError("Entrada de rastreabilidade não encontrada.")

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT TOP 1 id, user_id, conversation_id, trace_type,
                   question, answer, intent,
                   target_docs_json, retrieved_sources_json, generation_sources_json,
                   regulatory_session_id, regulatory_step, download_name,
                   result, error_type, severity, reviewer_notes,
                   created_at, updated_at
              FROM dbo.traceability_matrix
             WHERE id = ?
            """,
            trace_id,
        )
        row = cur.fetchone()

    if not row:
        raise ValueError("Entrada de rastreabilidade desapareceu após update.")

    return {
        "id": str(row[0]),
        "user_id": str(row[1]),
        "conversation_id": row[2],
        "trace_type": row[3],
        "question": row[4],
        "answer": row[5],
        "intent": row[6],
        "target_docs": _json_load(row[7]) or [],
        "retrieved_sources": _json_load(row[8]) or [],
        "generation_sources": _json_load(row[9]) or [],
        "regulatory_session_id": row[10],
        "regulatory_step": row[11],
        "download_name": row[12],
        "result": row[13],
        "error_type": row[14],
        "severity": row[15],
        "reviewer_notes": row[16],
        "created_at": _iso(row[17]),
        "updated_at": _iso(row[18]),
    }


def update_traceability_review(
    *,
    trace_id: str,
    user_id: str,
    result: Optional[str],
    error_type: Optional[str],
    severity: Optional[str],
    reviewer_notes: Optional[str],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE dbo.traceability_matrix
               SET result = ?,
                   error_type = ?,
                   severity = ?,
                   reviewer_notes = ?,
                   updated_at = ?
             WHERE id = ? AND user_id = ?
            """,
            result,
            error_type,
            severity,
            reviewer_notes,
            now,
            trace_id,
            user_id,
        )

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT TOP 1 id, user_id, conversation_id, trace_type,
                   question, answer, intent,
                   target_docs_json, retrieved_sources_json, generation_sources_json,
                   regulatory_session_id, regulatory_step, download_name,
                   result, error_type, severity, reviewer_notes,
                   created_at, updated_at
              FROM dbo.traceability_matrix
             WHERE id = ? AND user_id = ?
            """,
            trace_id,
            user_id,
        )
        row = cur.fetchone()

    if not row:
        raise ValueError("Entrada de rastreabilidade não encontrada.")

    return {
        "id": str(row[0]),
        "user_id": str(row[1]),
        "conversation_id": row[2],
        "trace_type": row[3],
        "question": row[4],
        "answer": row[5],
        "intent": row[6],
        "target_docs": _json_load(row[7]) or [],
        "retrieved_sources": _json_load(row[8]) or [],
        "generation_sources": _json_load(row[9]) or [],
        "regulatory_session_id": row[10],
        "regulatory_step": row[11],
        "download_name": row[12],
        "result": row[13],
        "error_type": row[14],
        "severity": row[15],
        "reviewer_notes": row[16],
        "created_at": _iso(row[17]),
        "updated_at": _iso(row[18]),
    }