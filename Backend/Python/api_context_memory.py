"""
Context Memory do BridgeMedAI.

Persistência estruturada do conhecimento que o Regulatory Documentation Copilot
acumula sobre cada dispositivo médico em conversa com o utilizador:

- `product_profiles`     — uma entrada por produto/conversa
- `extracted_fields`     — key-value de campos canónicos (intended_purpose, ...)
- `document_instances`   — instâncias de templates com lifecycle (draft/partial/...)
- `documentation_state`  — snapshot agregado do progresso documental

Esta camada é aditiva ao sistema existente: não toca em endpoints regulatórios,
RAG, traceability ou auth. Usa o mesmo padrão `db_cursor` do `api_db.py` e o
mesmo SQL Server.

Inclui também um extrator opcional baseado no LLM já configurado (Ollama) que
tenta inferir campos canónicos a partir de um excerto de conversa, sem auto-save
(o caller decide se persiste).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from api_db import db_cursor
from api_template_registry import all_records

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------
_DDL_PATH = (
    Path(__file__).resolve().parents[2] / "Database" / "02_context_memory.sql"
)


def _ddl_statements() -> List[str]:
    """Lê o ficheiro de migração e parte por separador `GO` para execução
    em lote pelo pyodbc (que não suporta `GO` nem múltiplos batches numa
    única chamada `execute`)."""
    if not _DDL_PATH.exists():
        raise RuntimeError(f"Migration não encontrada: {_DDL_PATH}")

    raw = _DDL_PATH.read_text(encoding="utf-8")
    # Remove a linha `USE BridgeMedAI;` que a ligação já tem implícita
    raw = re.sub(r"(?im)^\s*USE\s+\w+\s*;?\s*$", "", raw)
    parts = re.split(r"(?im)^\s*GO\s*$", raw)
    statements = [p.strip() for p in parts if p.strip()]
    return statements


def init_context_memory_schema() -> None:
    """Executa o DDL idempotente do Context Memory. Chamar no startup da API."""
    statements = _ddl_statements()
    with db_cursor(commit=True) as cur:
        for stmt in statements:
            cur.execute(stmt)


# ---------------------------------------------------------------------------
# Catálogo de campos canónicos (derivado do registry)
# ---------------------------------------------------------------------------
def canonical_field_keys() -> List[str]:
    """Devolve a união ordenada de todos os field keys que algum template
    declara como auto_fillable_fields ou human_required_fields."""
    seen: Set[str] = set()
    for record in all_records():
        for k in record.auto_fillable_fields:
            seen.add(k)
        for k in record.human_required_fields:
            seen.add(k)
    return sorted(seen)


def templates_using_field(field_key: str) -> List[Dict[str, str]]:
    """Devolve a lista de templates que declaram este field_key."""
    out: List[Dict[str, str]] = []
    for record in all_records():
        if field_key in record.auto_fillable_fields or field_key in record.human_required_fields:
            role = "auto_fillable" if field_key in record.auto_fillable_fields else "human_required"
            out.append({"id": record.id, "name": record.name, "category": record.category, "role": role})
    return out


# ---------------------------------------------------------------------------
# Serialização auxiliar
# ---------------------------------------------------------------------------
def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)


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


# ---------------------------------------------------------------------------
# product_profiles
# ---------------------------------------------------------------------------
_VALID_MDR_CLASSES = {"I", "IIa", "IIb", "III"}


def _profile_row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": str(row[0]),
        "user_id": str(row[1]),
        "conversation_id": row[2],
        "name": row[3],
        "mdr_class": row[4],
        "ai_system_flag": bool(row[5]) if row[5] is not None else None,
        "summary": row[6],
        "created_at": _iso(row[7]),
        "updated_at": _iso(row[8]),
    }


_PROFILE_SELECT_COLS = (
    "id, user_id, conversation_id, name, mdr_class, ai_system_flag, summary, created_at, updated_at"
)


def create_profile(
    *,
    user_id: str,
    conversation_id: Optional[str] = None,
    name: Optional[str] = None,
    mdr_class: Optional[str] = None,
    ai_system_flag: Optional[bool] = None,
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    if mdr_class is not None and mdr_class not in _VALID_MDR_CLASSES:
        raise ValueError(f"mdr_class inválido: {mdr_class}")

    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO dbo.product_profiles
                (id, user_id, conversation_id, name, mdr_class, ai_system_flag, summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            profile_id, user_id, conversation_id, name, mdr_class,
            ai_system_flag, summary, now, now,
        )

    return get_profile(profile_id=profile_id, user_id=user_id)


def get_profile(*, profile_id: str, user_id: str) -> Dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT TOP 1 {_PROFILE_SELECT_COLS} FROM dbo.product_profiles WHERE id = ? AND user_id = ?",
            profile_id, user_id,
        )
        row = cur.fetchone()

    if not row:
        raise KeyError(f"Profile '{profile_id}' não encontrado.")
    return _profile_row_to_dict(row)


def get_or_create_profile_for_conversation(
    *,
    user_id: str,
    conversation_id: str,
) -> Dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT TOP 1 {_PROFILE_SELECT_COLS}
              FROM dbo.product_profiles
             WHERE user_id = ? AND conversation_id = ?
             ORDER BY updated_at DESC
            """,
            user_id, conversation_id,
        )
        row = cur.fetchone()

    if row:
        return _profile_row_to_dict(row)
    return create_profile(user_id=user_id, conversation_id=conversation_id)


def list_profiles(*, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT TOP (?) {_PROFILE_SELECT_COLS}
              FROM dbo.product_profiles
             WHERE user_id = ?
             ORDER BY updated_at DESC
            """,
            limit, user_id,
        )
        rows = cur.fetchall()
    return [_profile_row_to_dict(r) for r in rows]


def update_profile_core(
    *,
    profile_id: str,
    user_id: str,
    name: Optional[str] = None,
    mdr_class: Optional[str] = None,
    ai_system_flag: Optional[bool] = None,
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    if mdr_class is not None and mdr_class not in _VALID_MDR_CLASSES:
        raise ValueError(f"mdr_class inválido: {mdr_class}")

    sets: List[str] = []
    params: List[Any] = []
    for col, val in (
        ("name", name),
        ("mdr_class", mdr_class),
        ("ai_system_flag", ai_system_flag),
        ("summary", summary),
    ):
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)

    if not sets:
        return get_profile(profile_id=profile_id, user_id=user_id)

    sets.append("updated_at = ?")
    params.append(datetime.now(timezone.utc))
    params.extend([profile_id, user_id])

    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE dbo.product_profiles SET {', '.join(sets)} WHERE id = ? AND user_id = ?",
            *params,
        )
        if cur.rowcount == 0:
            raise KeyError(f"Profile '{profile_id}' não encontrado.")

    return get_profile(profile_id=profile_id, user_id=user_id)


def delete_profile(*, profile_id: str, user_id: str) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM dbo.product_profiles WHERE id = ? AND user_id = ?",
            profile_id, user_id,
        )
        if cur.rowcount == 0:
            raise KeyError(f"Profile '{profile_id}' não encontrado.")


# ---------------------------------------------------------------------------
# extracted_fields
# ---------------------------------------------------------------------------
_VALID_FIELD_SOURCES = {"conversation", "manual", "document", "analysis", "llm"}


def _ensure_profile(profile_id: str, user_id: str) -> None:
    # Levanta KeyError se não pertencer ao user.
    get_profile(profile_id=profile_id, user_id=user_id)


def set_field(
    *,
    profile_id: str,
    user_id: str,
    field_key: str,
    field_value: Optional[str],
    source: str = "manual",
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    if not field_key or not field_key.strip():
        raise ValueError("field_key não pode estar vazio.")
    if source not in _VALID_FIELD_SOURCES:
        raise ValueError(f"source inválida: {source}")

    _ensure_profile(profile_id, user_id)
    now = datetime.now(timezone.utc)
    key = field_key.strip()

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE dbo.extracted_fields
               SET field_value = ?, source = ?, confidence = ?, updated_at = ?
             WHERE product_profile_id = ? AND field_key = ?
            """,
            field_value, source, confidence, now, profile_id, key,
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO dbo.extracted_fields
                    (id, product_profile_id, field_key, field_value, source, confidence, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                str(uuid.uuid4()), profile_id, key, field_value, source, confidence, now, now,
            )

        # Toca updated_at do profile para ordenar listas por mais recente
        cur.execute(
            "UPDATE dbo.product_profiles SET updated_at = ? WHERE id = ?",
            now, profile_id,
        )

    return get_field(profile_id=profile_id, user_id=user_id, field_key=key)


def get_field(
    *,
    profile_id: str,
    user_id: str,
    field_key: str,
) -> Dict[str, Any]:
    _ensure_profile(profile_id, user_id)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT TOP 1 id, product_profile_id, field_key, field_value, source, confidence, created_at, updated_at
              FROM dbo.extracted_fields
             WHERE product_profile_id = ? AND field_key = ?
            """,
            profile_id, field_key,
        )
        row = cur.fetchone()

    if not row:
        raise KeyError(f"Field '{field_key}' não existe no profile.")
    return {
        "id": str(row[0]),
        "product_profile_id": str(row[1]),
        "field_key": row[2],
        "field_value": row[3],
        "source": row[4],
        "confidence": float(row[5]) if row[5] is not None else None,
        "created_at": _iso(row[6]),
        "updated_at": _iso(row[7]),
    }


def list_fields(*, profile_id: str, user_id: str) -> List[Dict[str, Any]]:
    _ensure_profile(profile_id, user_id)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, product_profile_id, field_key, field_value, source, confidence, created_at, updated_at
              FROM dbo.extracted_fields
             WHERE product_profile_id = ?
             ORDER BY field_key
            """,
            profile_id,
        )
        rows = cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "product_profile_id": str(r[1]),
            "field_key": r[2],
            "field_value": r[3],
            "source": r[4],
            "confidence": float(r[5]) if r[5] is not None else None,
            "created_at": _iso(r[6]),
            "updated_at": _iso(r[7]),
        }
        for r in rows
    ]


def delete_field(*, profile_id: str, user_id: str, field_key: str) -> None:
    _ensure_profile(profile_id, user_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM dbo.extracted_fields WHERE product_profile_id = ? AND field_key = ?",
            profile_id, field_key,
        )
        if cur.rowcount == 0:
            raise KeyError(f"Field '{field_key}' não existe.")


# ---------------------------------------------------------------------------
# document_instances
# ---------------------------------------------------------------------------
_VALID_DOC_STATES = {"draft", "partial", "awaiting", "reviewed", "approved", "exported"}


def _instance_row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": str(row[0]),
        "product_profile_id": str(row[1]),
        "template_id": row[2],
        "state": row[3],
        "file_path": row[4],
        "download_name": row[5],
        "notes": row[6],
        "last_review_at": _iso(row[7]),
        "created_at": _iso(row[8]),
        "updated_at": _iso(row[9]),
    }


_INSTANCE_COLS = (
    "id, product_profile_id, template_id, state, file_path, download_name, notes, "
    "last_review_at, created_at, updated_at"
)
_INSTANCE_COLS_DI = (
    "di.id, di.product_profile_id, di.template_id, di.state, di.file_path, di.download_name, di.notes, "
    "di.last_review_at, di.created_at, di.updated_at"
)


def create_instance(
    *,
    profile_id: str,
    user_id: str,
    template_id: str,
    state: str = "draft",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    if state not in _VALID_DOC_STATES:
        raise ValueError(f"Estado inválido: {state}")
    _ensure_profile(profile_id, user_id)

    instance_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO dbo.document_instances
                (id, product_profile_id, template_id, state, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            instance_id, profile_id, template_id, state, notes, now, now,
        )
        cur.execute(
            "UPDATE dbo.product_profiles SET updated_at = ? WHERE id = ?",
            now, profile_id,
        )

    return get_instance(instance_id=instance_id, user_id=user_id)


def get_instance(*, instance_id: str, user_id: str) -> Dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT TOP 1 {_INSTANCE_COLS_DI}
              FROM dbo.document_instances di
              JOIN dbo.product_profiles pp ON pp.id = di.product_profile_id
             WHERE di.id = ? AND pp.user_id = ?
            """,
            instance_id, user_id,
        )
        row = cur.fetchone()
    if not row:
        raise KeyError(f"Document instance '{instance_id}' não encontrada.")
    return _instance_row_to_dict(row)


def list_instances(*, profile_id: str, user_id: str) -> List[Dict[str, Any]]:
    _ensure_profile(profile_id, user_id)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_INSTANCE_COLS}
              FROM dbo.document_instances
             WHERE product_profile_id = ?
             ORDER BY updated_at DESC
            """,
            profile_id,
        )
        rows = cur.fetchall()
    return [_instance_row_to_dict(r) for r in rows]


def update_instance(
    *,
    instance_id: str,
    user_id: str,
    state: Optional[str] = None,
    file_path: Optional[str] = None,
    download_name: Optional[str] = None,
    notes: Optional[str] = None,
    mark_reviewed: bool = False,
) -> Dict[str, Any]:
    if state is not None and state not in _VALID_DOC_STATES:
        raise ValueError(f"Estado inválido: {state}")

    # Confirma ownership antes de atualizar
    get_instance(instance_id=instance_id, user_id=user_id)

    sets: List[str] = []
    params: List[Any] = []
    for col, val in (
        ("state", state),
        ("file_path", file_path),
        ("download_name", download_name),
        ("notes", notes),
    ):
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)

    now = datetime.now(timezone.utc)
    if mark_reviewed:
        sets.append("last_review_at = ?")
        params.append(now)

    if not sets:
        return get_instance(instance_id=instance_id, user_id=user_id)

    sets.append("updated_at = ?")
    params.append(now)
    params.append(instance_id)

    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE dbo.document_instances SET {', '.join(sets)} WHERE id = ?",
            *params,
        )

    return get_instance(instance_id=instance_id, user_id=user_id)


def delete_instance(*, instance_id: str, user_id: str) -> None:
    # Valida ownership.
    get_instance(instance_id=instance_id, user_id=user_id)
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM dbo.document_instances WHERE id = ?", instance_id)


# ---------------------------------------------------------------------------
# documentation_state (snapshot agregado)
# ---------------------------------------------------------------------------
def _state_row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "product_profile_id": str(row[0]),
        "missing_information": _json_load(row[1]) or [],
        "pending_sections": _json_load(row[2]) or {},
        "progress_percent": int(row[3]) if row[3] is not None else None,
        "notes": row[4],
        "updated_at": _iso(row[5]),
    }


def get_documentation_state(*, profile_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    _ensure_profile(profile_id, user_id)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT TOP 1 product_profile_id, missing_information_json, pending_sections_json,
                         progress_percent, notes, updated_at
              FROM dbo.documentation_state
             WHERE product_profile_id = ?
            """,
            profile_id,
        )
        row = cur.fetchone()
    if not row:
        return None
    return _state_row_to_dict(row)


def upsert_documentation_state(
    *,
    profile_id: str,
    user_id: str,
    missing_information: Optional[List[Any]] = None,
    pending_sections: Optional[Dict[str, Any]] = None,
    progress_percent: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_profile(profile_id, user_id)
    now = datetime.now(timezone.utc)
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE dbo.documentation_state
               SET missing_information_json = ?,
                   pending_sections_json = ?,
                   progress_percent = ?,
                   notes = ?,
                   updated_at = ?
             WHERE product_profile_id = ?
            """,
            _json_dump(missing_information),
            _json_dump(pending_sections),
            progress_percent,
            notes,
            now,
            profile_id,
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO dbo.documentation_state
                    (product_profile_id, missing_information_json, pending_sections_json,
                     progress_percent, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                profile_id,
                _json_dump(missing_information),
                _json_dump(pending_sections),
                progress_percent,
                notes,
                now,
            )

    return get_documentation_state(profile_id=profile_id, user_id=user_id) or {}


def recompute_documentation_state(
    *,
    profile_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Calcula `documentation_state` a partir do registry + extracted_fields +
    document_instances atuais. Recolhe campos em falta dos templates já
    iniciados (instâncias) e devolve a percentagem global de preenchimento."""
    instances = list_instances(profile_id=profile_id, user_id=user_id)
    fields = list_fields(profile_id=profile_id, user_id=user_id)
    have_keys: Set[str] = {f["field_key"] for f in fields if f["field_value"]}

    records_by_id = {r.id: r for r in all_records()}

    missing: List[Dict[str, Any]] = []
    pending_sections: Dict[str, List[str]] = {}
    total_required = 0
    covered = 0

    for inst in instances:
        record = records_by_id.get(inst["template_id"])
        if not record:
            continue
        required = list(record.auto_fillable_fields) + list(record.human_required_fields)
        per_template_missing: List[str] = []
        for key in required:
            total_required += 1
            if key in have_keys:
                covered += 1
            else:
                per_template_missing.append(key)
        if per_template_missing:
            pending_sections[record.id] = per_template_missing
            for key in per_template_missing:
                missing.append({"field_key": key, "needed_by": record.id})

    progress = int(round((covered / total_required) * 100)) if total_required else None

    return upsert_documentation_state(
        profile_id=profile_id,
        user_id=user_id,
        missing_information=missing,
        pending_sections=pending_sections,
        progress_percent=progress,
        notes=None,
    )


# ---------------------------------------------------------------------------
# Snapshot completo (perfil + fields + instances + state)
# ---------------------------------------------------------------------------
def get_profile_snapshot(*, profile_id: str, user_id: str) -> Dict[str, Any]:
    profile = get_profile(profile_id=profile_id, user_id=user_id)
    fields = list_fields(profile_id=profile_id, user_id=user_id)
    instances = list_instances(profile_id=profile_id, user_id=user_id)
    state = get_documentation_state(profile_id=profile_id, user_id=user_id)
    return {
        "profile": profile,
        "fields": fields,
        "documents": instances,
        "documentation_state": state,
    }


# ---------------------------------------------------------------------------
# Extrator LLM opcional (opt-in)
# ---------------------------------------------------------------------------
_DEFAULT_EXTRACTABLE_FIELDS = [
    "intended_purpose",
    "indications",
    "contraindications",
    "target_population",
    "user_profiles",
    "device_description",
    "classification_mdr",
    "ai_capabilities",
    "software_modules",
    "use_environment",
    "clinical_benefits",
    "residual_risks",
]


def _extraction_system_prompt(field_keys: List[str]) -> str:
    return (
        "És um extrator de informação regulatória para dispositivos médicos. "
        "Recebes um excerto de conversa entre um utilizador e um copiloto regulatório. "
        "Devolves APENAS um objeto JSON válido, sem markdown, sem comentários, sem prefixo. "
        "As chaves do JSON devem ser exatamente as fornecidas: "
        f"{', '.join(field_keys)}. "
        "Para cada chave: se o excerto contiver informação clara e direta sobre esse campo, "
        "põe o valor como string curta (1-3 frases). Se NÃO houver informação, "
        "põe `null`. Não inventes nada. Não copies texto irrelevante. Responde só com o JSON."
    )


def _try_parse_json_object(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    # remover code fences
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def extract_fields_from_text(
    text: str,
    *,
    field_keys: Optional[List[str]] = None,
) -> Dict[str, Optional[str]]:
    """Tenta extrair campos canónicos de um excerto de texto usando o LLM
    Ollama configurado em `OLLAMA_CHAT_MODEL`. Devolve `{key: value or None}`.

    Não persiste nada — o caller decide se chama `set_field()` para cada
    campo extraído. Em caso de qualquer erro do LLM, devolve dict vazio."""
    if not text or not text.strip():
        return {}

    chat_model = os.getenv("OLLAMA_CHAT_MODEL")
    if not chat_model:
        return {}

    keys = field_keys or _DEFAULT_EXTRACTABLE_FIELDS

    try:
        import ollama  # type: ignore

        response = ollama.chat(
            model=chat_model,
            messages=[
                {"role": "system", "content": _extraction_system_prompt(keys)},
                {"role": "user", "content": text},
            ],
            stream=False,
            format="json",
        )
    except Exception:
        return {}

    raw = ""
    try:
        raw = response["message"]["content"]  # type: ignore[index]
    except Exception:
        return {}

    data = _try_parse_json_object(raw)
    out: Dict[str, Optional[str]] = {}
    for k in keys:
        value = data.get(k)
        if value is None:
            out[k] = None
        elif isinstance(value, (str, int, float, bool)):
            v_str = str(value).strip()
            out[k] = v_str if v_str else None
        elif isinstance(value, (list, dict)):
            try:
                out[k] = json.dumps(value, ensure_ascii=False)
            except Exception:
                out[k] = None
        else:
            out[k] = None
    return out
