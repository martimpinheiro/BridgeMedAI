"""
Questionnaire controller para o Regulatory Documentation Copilot.

Quando o utilizador, dentro da conversa, aceita "Preencher por mim" para um
ou mais templates, este módulo:

1. **Lê o(s) template(s) selecionado(s) do disco** e extrai os placeholders
   `<...>` reais que o autor humano costuma preencher (nome do produto,
   versão, etc. — não inventa perguntas).
2. Cria uma sessão (em memória) com a fila de placeholders.
3. Deduplica placeholders entre templates da mesma sessão (se 2 templates
   pedem `<name of the product>`, só pergunta uma vez).
4. Devolve a próxima pergunta `{question, hint, context, progress}`.
5. Quando o utilizador responde, guarda o valor e passa à próxima.
6. No fim, dispara `autofill_instance` que substitui literalmente cada
   `<...>` pelo valor recolhido e devolve os download links.

Sessões em memória — em produção persistir-se-iam.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from api_template_registry import get_record, get_template_file_path
from api_template_placeholders import (
    Placeholder,
    extract_placeholders,
    humanize_placeholder_text,
)
from api_context_memory import (
    create_instance,
    get_or_create_profile_for_conversation,
    list_instances,
)
from api_autofill_engine import AutofillError, autofill_instance


# ---------------------------------------------------------------------------
# Estado de sessão (em memória)
# ---------------------------------------------------------------------------
@dataclass
class QuestionnaireSession:
    id: str
    user_id: str
    profile_id: str
    conversation_id: Optional[str]
    template_ids: List[str]
    instance_ids: Dict[str, str]                       # template_id -> instance_id
    placeholders_by_template: Dict[str, List[Placeholder]]  # template_id -> all placeholders
    # Fila de "perguntas únicas" (uma por chave normalizada). Cada entrada
    # contém o placeholder de referência (para texto + contexto) + lista de
    # ocorrências reais que essa pergunta resolve (para depois substituir
    # no autofill).
    question_queue: List[Dict[str, Any]] = field(default_factory=list)
    answered: Dict[str, str] = field(default_factory=dict)  # normalized_key -> answer
    current_index: int = 0
    completed: bool = False
    generated_files: List[Dict[str, Any]] = field(default_factory=list)


_sessions: Dict[str, QuestionnaireSession] = {}
_sessions_lock = threading.Lock()


def _get_session(session_id: str, user_id: str) -> QuestionnaireSession:
    with _sessions_lock:
        s = _sessions.get(session_id)
    if not s:
        raise KeyError(f"Sessão de questionário '{session_id}' não existe.")
    if s.user_id != user_id:
        raise PermissionError("Sessão não pertence a este utilizador.")
    return s


# ---------------------------------------------------------------------------
# Construção da fila a partir dos placeholders
# ---------------------------------------------------------------------------
def _norm_key(raw_text: str, context: str = "") -> str:
    """
    Chave de deduplicação.

    Campos globais como nome do produto, versão, fabricante, Basic UDI-DI
    devem ser deduplicados entre templates.
    Campos genéricos como 'enter number between 0 and 3' devem incluir contexto,
    senão perguntas diferentes podem colapsar numa só.
    """
    import re

    raw_norm = re.sub(r"\s+", " ", raw_text or "").strip().lower()
    ctx_norm = re.sub(r"\s+", " ", context or "").strip().lower()

    global_fields = {
        "name of the product",
        "product name",
        "device name",
        "version of the product",
        "version of the software",
        "software version",
        "basic udi-di, if/when available",
        "company",
        "manufacturer",
        "manufacturer name",
    }

    if raw_norm in global_fields:
        return raw_norm

    if raw_norm.startswith("enter number between"):
        return f"{raw_norm}::{ctx_norm}"

    return raw_norm

def _build_question_queue(
    placeholders_by_template: Dict[str, List[Placeholder]],
) -> List[Dict[str, Any]]:
    """Constrói lista de perguntas únicas. Cada pergunta tem:
        - norm_key: chave para deduplicar entre templates
        - reference: Placeholder de referência (para texto/contexto)
        - occurrences: lista de tuplos (template_id, placeholder) a substituir
    """
    by_norm: Dict[str, Dict[str, Any]] = {}
    order_counter = 0

    # Iteramos templates pela ordem com que foram pedidos; dentro de cada
    # template, pela ordem do placeholder no documento.
    for template_id, phs in placeholders_by_template.items():
        for ph in phs:
            nk = _norm_key(ph.raw_text, ph.context)
            if nk in by_norm:
                by_norm[nk]["occurrences"].append((template_id, ph))
                continue
            order_counter += 1
            by_norm[nk] = {
                "norm_key": nk,
                "reference": ph,
                "occurrences": [(template_id, ph)],
                "order": order_counter,
            }

    return sorted(by_norm.values(), key=lambda x: x["order"])


def _ensure_instances(
    profile_id: str,
    user_id: str,
    template_ids: List[str],
) -> Dict[str, str]:
    existing = {i["template_id"]: i["id"] for i in list_instances(profile_id=profile_id, user_id=user_id)}
    result: Dict[str, str] = {}
    for tid in template_ids:
        if tid in existing:
            result[tid] = existing[tid]
            continue
        try:
            get_record(tid)
        except KeyError:
            continue
        instance = create_instance(
            profile_id=profile_id,
            user_id=user_id,
            template_id=tid,
            state="draft",
            notes="Iniciado pelo questionário do Copilot (placeholders reais).",
        )
        result[tid] = instance["id"]
    return result


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def start_questionnaire(
    *,
    user_id: str,
    conversation_id: Optional[str],
    template_ids: List[str],
) -> Dict[str, Any]:
    if not template_ids:
        raise ValueError("Tens de indicar pelo menos um template.")

    # validar templates + extrair placeholders
    placeholders_by_template: Dict[str, List[Placeholder]] = {}
    valid_ids: List[str] = []
    for tid in template_ids:
        try:
            get_record(tid)
        except KeyError:
            continue
        try:
            path = get_template_file_path(tid)
        except Exception:
            continue
        if path.suffix.lower() != ".docx":
            continue  # .xlsx ainda não suportado
        try:
            phs = extract_placeholders(path)
        except Exception:
            phs = []
        placeholders_by_template[tid] = phs
        valid_ids.append(tid)

    if not valid_ids:
        raise ValueError("Nenhum dos templates indicados é compatível (.docx) ou existe.")

    # Garantir profile + instâncias
    profile = get_or_create_profile_for_conversation(
        user_id=user_id,
        conversation_id=conversation_id or f"questionnaire-{uuid.uuid4()}",
    )
    profile_id = profile["id"]
    instance_ids = _ensure_instances(profile_id, user_id, valid_ids)

    # Fila de perguntas únicas
    queue = _build_question_queue(placeholders_by_template)

    session_id = str(uuid.uuid4())
    session = QuestionnaireSession(
        id=session_id,
        user_id=user_id,
        profile_id=profile_id,
        conversation_id=conversation_id,
        template_ids=valid_ids,
        instance_ids=instance_ids,
        placeholders_by_template=placeholders_by_template,
        question_queue=queue,
    )
    with _sessions_lock:
        _sessions[session_id] = session

    if not queue:
        # Templates não têm placeholders <...> — vai direto para autofill
        # (que vai gerar com cover sheet apenas)
        return _complete_and_generate(session)

    return _build_question_response(session)


def answer_current_question(
    *,
    session_id: str,
    user_id: str,
    answer_text: str,
) -> Dict[str, Any]:
    session = _get_session(session_id, user_id)
    if session.completed:
        return _build_completion_response(session)
    if session.current_index >= len(session.question_queue):
        return _complete_and_generate(session)

    current = session.question_queue[session.current_index]
    answer_text = (answer_text or "").strip()
    skip = answer_text.lower() in {"skip", "passar", "saltar", "não sei", "nao sei", "n/a"}
    if not skip and answer_text:
        session.answered[current["norm_key"]] = answer_text

    session.current_index += 1
    if session.current_index >= len(session.question_queue):
        return _complete_and_generate(session)

    return _build_question_response(session)


def get_session_state(*, session_id: str, user_id: str) -> Dict[str, Any]:
    session = _get_session(session_id, user_id)
    if session.completed:
        return _build_completion_response(session)
    if session.current_index < len(session.question_queue):
        return _build_question_response(session)
    return {"session_id": session.id, "state": "idle"}


def cancel_session(*, session_id: str, user_id: str) -> Dict[str, Any]:
    session = _get_session(session_id, user_id)
    with _sessions_lock:
        _sessions.pop(session_id, None)
    return {
        "session_id": session.id,
        "state": "cancelled",
        "answered_count": len(session.answered),
    }


# ---------------------------------------------------------------------------
# Builders de resposta
# ---------------------------------------------------------------------------
def _build_question_response(session: QuestionnaireSession) -> Dict[str, Any]:
    current = session.question_queue[session.current_index]
    ph: Placeholder = current["reference"]
    occurrences = current["occurrences"]

    contexts = sorted({occ[1].context for occ in occurrences if occ[1].context})
    context_text = ", ".join(contexts)

    question = humanize_placeholder_text(ph.raw_text, context_text)
    where_in = sorted({get_record(occ[0]).name for occ in occurrences})

    total = len(session.question_queue)
    answered = session.current_index
    pct = int(round((answered / total) * 100)) if total else 100

    templates_info = [{"id": tid, "name": get_record(tid).name} for tid in session.template_ids]

    return {
        "session_id": session.id,
        "state": "asking",
        "question": question,
        "hint": (
            f"Secção do template: {context_text}."
            if context_text
            else "Campo extraído do template."
        ),
        "placeholder_raw": ph.raw_text,
        "context": ", ".join(contexts) if contexts else None,
        "used_in": where_in,
        "progress": {"answered": answered, "total": total, "percent": pct},
        "templates": templates_info,
    }


def _complete_and_generate(session: QuestionnaireSession) -> Dict[str, Any]:
    """Marca sessão como completa e gera o .docx de cada template, com as
    substituições reais de `<...>` pelos valores recolhidos."""
    session.completed = True
    generated: List[Dict[str, Any]] = []

    # Construir mapping por template: full_match -> answer
    for template_id, instance_id in session.instance_ids.items():
        substitutions: Dict[str, str] = {}
        for ph in session.placeholders_by_template.get(template_id, []):
            nk = _norm_key(ph.raw_text, ph.context)
            ans = session.answered.get(nk)
            if ans:
                substitutions[ph.full_match] = ans

        try:
            result = autofill_instance(
                instance_id=instance_id,
                user_id=session.user_id,
                placeholder_substitutions=substitutions,
            )
            generated.append({
                "template_id": template_id,
                "template_name": result["template"]["name"],
                "instance_id": instance_id,
                "download_name": result["instance"].get("download_name"),
                "download_url": f"/memory/documents/{instance_id}/download",
                "state": result["instance"].get("state"),
                "substituted_count": len(substitutions),
                "ok": True,
            })
        except AutofillError as exc:
            generated.append({
                "template_id": template_id,
                "instance_id": instance_id,
                "ok": False,
                "error": str(exc),
            })
        except Exception as exc:
            generated.append({
                "template_id": template_id,
                "instance_id": instance_id,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            })

    session.generated_files = generated
    return _build_completion_response(session)


def _build_completion_response(session: QuestionnaireSession) -> Dict[str, Any]:
    return {
        "session_id": session.id,
        "state": "completed",
        "answered_count": len(session.answered),
        "generated_files": session.generated_files,
    }
