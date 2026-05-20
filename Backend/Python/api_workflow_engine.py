"""
Workflow Engine do BridgeMedAI.

Camada que entende dependências entre templates (grafo `dependencies` /
`feeds_into` do registry) e propõe **workflows multi-documento** para o perfil
regulatório atual.

Funcionalidades:

- `expand_dependencies(id)` / `expand_downstream(id)`: travessia BFS no grafo
  com guarda de ciclos.
- `BASE_WORKFLOWS`: blocos predefinidos por contexto regulatório
  (`minimal`, `software`, `ai`, `post_market`, `usability_intensive`).
- `recommend_path_for_profile`: combina blocos consoante classe MDR, uso de
  IA e presença de software no perfil.
- `validate_started_workflow`: dada a lista de instâncias já iniciadas,
  identifica dependências em falta.
- `apply_workflow`: cria em bulk as `document_instances` dos templates
  recomendados que ainda não existem.

Tudo aditivo: não toca em endpoints/lógica existentes, e respeita o registry
seed atual (templates com `metadata_status='seed'` continuam a alimentar o
grafo, mas os warnings deixam isso claro).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from api_template_registry import TemplateRecord, all_records, get_record
from api_context_memory import (
    create_instance as cm_create_instance,
    get_profile,
    list_fields,
    list_instances,
)

# ---------------------------------------------------------------------------
# Workflow paths predefinidos (ordem importa)
# ---------------------------------------------------------------------------
# Cada bloco é uma sequência de template_ids; quando combinados, a ordem
# global preserva a posição da primeira ocorrência.
BASE_WORKFLOWS: Dict[str, List[str]] = {
    # Foundation regulatório — aplicável a qualquer dispositivo
    "minimal": [
        "TMP-IU-02",   # Stakeholders Requirements
        "TMP-TD-03",   # GSPR checklist
        "TMP-RM-02",   # Risk Management Plan
        "TMP-RM-01",   # Risk Management File
        "TMP-RM-03",   # Risk Management Report
        "TMP-CE-02",   # Clinical Evaluation Plan
        "TMP-CE-04",   # Literature Search List
        "TMP-CE-01",   # Clinical Evaluation Report
    ],
    # Adições para dispositivos com software (MDSW)
    "software": [
        "FRM-SW-09",   # Software Safety Classification
        "TMP-SW-02",   # Software Development Plan
        "TMP-SW-04",   # SRS
        "FRM-SW-01",   # SRS Checklist
        "TMP-SW-05",   # Software Architecture
        "TMP-SW-06",   # System Test Protocol
        "FRM-SW-08",   # Design Review Checklist
        "FRM-SW-05",   # Software Release Checklist
    ],
    # Adições para sistemas com IA (AI Act)
    "ai": [
        "TMP-SW-08",   # Cybersecurity (geralmente requerido com IA)
    ],
    # Pós-mercado obrigatório para MDR (Anexo XIV Parte B, Art. 83 e Art. 87)
    "post_market": [
        "TMP-CE-05",   # PMCF Plan
        "TMP-CE-06",   # PMCF Report
        "SOP-CM-01",   # Feedback & Complaints procedure
        "SOP-VI-01",   # Vigilance procedure
        "FRM-VI-01",   # Incident Evaluation
    ],
    # Usability intensiva (recomendado para Class IIb/III ou para uso por leigos)
    "usability_intensive": [
        "TMP-HF-02",   # Usability Plan
        "TMP-HF-03",   # Usability Test Protocol
        "TMP-HF-04",   # Usability Test Report
        "TMP-HF-01",   # Usability Engineering File
    ],
    # QMS core (CAPA + change control) — recomendado para qualquer classe
    "qms_core": [
        "SOP-CC-01",   # Change Management procedure
        "FRM-CC-01",   # Change Request
        "SOP-CP-01",   # CAPA procedure
        "SOP-SW-02",   # Software Problem Resolution
    ],
}


# ---------------------------------------------------------------------------
# Grafo: travessias
# ---------------------------------------------------------------------------
def _index() -> Dict[str, TemplateRecord]:
    return {r.id: r for r in all_records()}


def expand_dependencies(template_id: str, *, max_depth: int = 6) -> List[str]:
    """Devolve todas as dependências transitivas (pré-requisitos) ordenadas
    em ordem topológica aproximada (deps mais profundas primeiro). Com
    cycle guard."""
    idx = _index()
    if template_id not in idx:
        return []

    order: List[str] = []
    seen: Set[str] = set()
    stack: List[Tuple[str, int]] = [(template_id, 0)]
    pending: Set[str] = set()

    def visit(tid: str, depth: int) -> None:
        if tid in seen or depth > max_depth:
            return
        if tid in pending:
            return  # cycle break
        pending.add(tid)
        record = idx.get(tid)
        if record:
            for dep in record.dependencies:
                if dep in idx and dep != template_id:
                    visit(dep, depth + 1)
                    if dep not in seen:
                        seen.add(dep)
                        order.append(dep)
        pending.discard(tid)

    visit(template_id, 0)
    return order


def expand_downstream(template_id: str, *, max_depth: int = 6) -> List[str]:
    """Devolve todos os documentos que dependem (direta ou transitivamente)
    deste — i.e. seguem a cadeia `feeds_into`."""
    idx = _index()
    if template_id not in idx:
        return []

    out: List[str] = []
    seen: Set[str] = set()
    queue: deque = deque([(template_id, 0)])

    while queue:
        tid, depth = queue.popleft()
        if depth > max_depth:
            continue
        record = idx.get(tid)
        if not record:
            continue
        for nxt in record.feeds_into:
            if nxt in idx and nxt not in seen and nxt != template_id:
                seen.add(nxt)
                out.append(nxt)
                queue.append((nxt, depth + 1))
    return out


def get_template_dependency_view(template_id: str) -> Dict[str, Any]:
    record = get_record(template_id)
    idx = _index()
    deps_ids = expand_dependencies(template_id)
    downstream_ids = expand_downstream(template_id)

    def _summary(ids: List[str]) -> List[Dict[str, str]]:
        out = []
        for tid in ids:
            r = idx.get(tid)
            if r:
                out.append({"id": r.id, "name": r.name, "category": r.category})
        return out

    return {
        "template": {"id": record.id, "name": record.name, "category": record.category},
        "direct_dependencies": [
            {"id": idx[d].id, "name": idx[d].name, "category": idx[d].category}
            for d in record.dependencies
            if d in idx
        ],
        "direct_feeds_into": [
            {"id": idx[d].id, "name": idx[d].name, "category": idx[d].category}
            for d in record.feeds_into
            if d in idx
        ],
        "transitive_dependencies": _summary(deps_ids),
        "transitive_downstream": _summary(downstream_ids),
    }


# ---------------------------------------------------------------------------
# Recomendação de path por contexto regulatório
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProfileContext:
    mdr_class: Optional[str]
    is_software: bool
    uses_ai: bool

    @classmethod
    def from_profile(cls, profile: Dict[str, Any], fields_by_key: Dict[str, str]) -> "ProfileContext":
        mdr_class = (profile.get("mdr_class") or fields_by_key.get("classification_mdr") or "").strip() or None
        # heurística simples — fields canónicos: software_modules / ai_capabilities
        is_software = bool(fields_by_key.get("software_modules"))
        ai_flag = profile.get("ai_system_flag")
        uses_ai = bool(ai_flag) if ai_flag is not None else bool(fields_by_key.get("ai_capabilities"))
        return cls(mdr_class=mdr_class, is_software=is_software, uses_ai=uses_ai)


def _dedupe(*sequences: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for seq in sequences:
        for tid in seq:
            if tid not in seen:
                seen.add(tid)
                out.append(tid)
    return out


def recommend_path(ctx: ProfileContext) -> Dict[str, Any]:
    """Combina os blocos `BASE_WORKFLOWS` conforme o contexto e devolve a
    sequência completa, anotando quais blocos foram aplicados."""
    blocks_applied: List[str] = ["minimal", "qms_core"]
    chunks: List[List[str]] = [BASE_WORKFLOWS["minimal"], BASE_WORKFLOWS["qms_core"]]

    if ctx.is_software or ctx.uses_ai:
        blocks_applied.append("software")
        chunks.append(BASE_WORKFLOWS["software"])

    if ctx.uses_ai:
        blocks_applied.append("ai")
        chunks.append(BASE_WORKFLOWS["ai"])

    if ctx.mdr_class in ("IIa", "IIb", "III"):
        blocks_applied.append("post_market")
        chunks.append(BASE_WORKFLOWS["post_market"])

    if ctx.mdr_class in ("IIb", "III"):
        blocks_applied.append("usability_intensive")
        chunks.append(BASE_WORKFLOWS["usability_intensive"])

    path = _dedupe(*chunks)

    idx = _index()
    sequence: List[Dict[str, Any]] = []
    for tid in path:
        record = idx.get(tid)
        if not record:
            continue
        sequence.append({
            "id": record.id,
            "name": record.name,
            "category": record.category,
            "doc_type": record.doc_type,
            "workflow_priority": record.workflow_priority,
            "direct_dependencies": list(record.dependencies),
        })

    return {
        "blocks_applied": blocks_applied,
        "context": {
            "mdr_class": ctx.mdr_class,
            "is_software": ctx.is_software,
            "uses_ai": ctx.uses_ai,
        },
        "sequence": sequence,
    }


# ---------------------------------------------------------------------------
# Validação de workflow em curso
# ---------------------------------------------------------------------------
def validate_started_workflow(
    started_template_ids: List[str],
) -> Dict[str, Any]:
    """Para cada instância iniciada, verifica se as dependências diretas
    também estão iniciadas. Devolve warnings agrupados."""
    idx = _index()
    started: Set[str] = set(started_template_ids)
    warnings: List[Dict[str, Any]] = []

    for tid in started_template_ids:
        record = idx.get(tid)
        if not record:
            continue
        for dep in record.dependencies:
            if dep in idx and dep not in started:
                warnings.append({
                    "template_id": tid,
                    "template_name": record.name,
                    "missing_dependency_id": dep,
                    "missing_dependency_name": idx[dep].name,
                    "missing_dependency_category": idx[dep].category,
                    "level": "warning",
                    "message": (
                        f"'{record.name}' depende de '{idx[dep].name}' que ainda não foi iniciado."
                    ),
                })

    return {
        "started_count": len(started),
        "warnings": warnings,
        "warning_count": len(warnings),
    }


# ---------------------------------------------------------------------------
# API alto-nível para um perfil
# ---------------------------------------------------------------------------
def _fields_dict(profile_id: str, user_id: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for f in list_fields(profile_id=profile_id, user_id=user_id):
        if f.get("field_value"):
            out[f["field_key"]] = f["field_value"]
    return out


def workflow_for_profile(*, profile_id: str, user_id: str) -> Dict[str, Any]:
    profile = get_profile(profile_id=profile_id, user_id=user_id)
    fields_by_key = _fields_dict(profile_id, user_id)
    ctx = ProfileContext.from_profile(profile, fields_by_key)

    recommendation = recommend_path(ctx)

    instances = list_instances(profile_id=profile_id, user_id=user_id)
    started_ids = [i["template_id"] for i in instances]
    started_set = set(started_ids)

    # Annotate which steps in the recommended path are already started
    for step in recommendation["sequence"]:
        step["already_started"] = step["id"] in started_set
        # Find the instance state if present (most recent)
        for inst in instances:
            if inst["template_id"] == step["id"]:
                step["instance_id"] = inst["id"]
                step["instance_state"] = inst["state"]
                step["instance_download_name"] = inst.get("download_name")
                break

    validation = validate_started_workflow(started_ids)

    # Computar "missing from recommendation" — templates recomendados ainda
    # não iniciados
    missing_from_recommendation = [
        step for step in recommendation["sequence"] if not step["already_started"]
    ]

    return {
        "profile": {
            "id": profile["id"],
            "name": profile.get("name"),
            "mdr_class": profile.get("mdr_class"),
            "ai_system_flag": profile.get("ai_system_flag"),
        },
        "recommendation": recommendation,
        "started_template_ids": started_ids,
        "missing_from_recommendation": missing_from_recommendation,
        "validation": validation,
    }


def apply_workflow(
    *,
    profile_id: str,
    user_id: str,
    template_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Cria em bulk as `document_instances` para os templates recomendados
    que ainda não existem no perfil. Se `template_ids` for fornecido, usa
    essa lista em vez da recomendação automática."""
    profile = get_profile(profile_id=profile_id, user_id=user_id)
    fields_by_key = _fields_dict(profile_id, user_id)
    ctx = ProfileContext.from_profile(profile, fields_by_key)

    if template_ids is None:
        recommendation = recommend_path(ctx)
        template_ids = [s["id"] for s in recommendation["sequence"]]

    existing = {
        i["template_id"]: i for i in list_instances(profile_id=profile_id, user_id=user_id)
    }

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for tid in template_ids:
        try:
            record = get_record(tid)
        except KeyError:
            skipped.append({"template_id": tid, "reason": "template não existe no registry"})
            continue

        if tid in existing:
            skipped.append({
                "template_id": tid,
                "reason": "já iniciado",
                "instance_id": existing[tid]["id"],
            })
            continue

        try:
            instance = cm_create_instance(
                profile_id=profile_id,
                user_id=user_id,
                template_id=tid,
                state="draft",
                notes=f"Adicionado pelo workflow {', '.join(['minimal'])} automático.",
            )
        except Exception as exc:
            skipped.append({"template_id": tid, "reason": str(exc)})
            continue

        created.append({
            "template_id": tid,
            "template_name": record.name,
            "instance_id": instance["id"],
        })

    return {
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }
