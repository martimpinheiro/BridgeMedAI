"""
Document Orchestrator do BridgeMedAI.

Camada de sugestão contextual de documentos para o Regulatory Documentation
Copilot. Dado um excerto de conversa (mensagem atual + histórico recente),
devolve uma lista de templates relevantes com:

- score semântico (do retrieval em ChromaDB);
- temas e regulamentos detetados explicitamente no texto;
- rationale legível ("porque foi sugerido");
- documentos pré-requisito (dependências) que o utilizador deve considerar
  antes ou em conjunto.

Este módulo é puro de orquestração — não toca em estado regulatório nem
gera resposta de chat. Pode ser chamado em paralelo com `/chat` sem
interferir com o fluxo existente.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from api_template_registry import (
    TemplateRecord,
    get_record,
    list_tags,
    search_templates,
)


# ---------------------------------------------------------------------------
# Sinónimos / variantes para deteção em texto natural (PT/EN)
# ---------------------------------------------------------------------------
_REGULATION_ALIASES: Dict[str, List[str]] = {
    "MDR": [
        "mdr",
        "regulamento 2017/745",
        "2017/745",
        "medical device regulation",
        "regulamento de dispositivos médicos",
    ],
    "AI_Act": [
        "ai act",
        "ai_act",
        "regulamento de ia",
        "2024/1689",
        "ai regulation",
        "lei da ia",
    ],
    "ISO_13485": ["iso 13485", "iso13485", "13485"],
    "ISO_14971": ["iso 14971", "14971", "risk management standard"],
    "ISO_14155": ["iso 14155", "14155", "clinical investigation standard"],
    "IEC_62304": ["iec 62304", "62304", "software lifecycle"],
    "IEC_62366": ["iec 62366", "62366", "usability engineering standard"],
    "IEC_82304": ["iec 82304", "82304", "health software"],
    "IEC_81001-5-1": ["81001", "81001-5-1", "cybersecurity standard"],
    "MEDDEV_2.7.1_rev4": ["meddev 2.7", "meddev 2.7/1", "meddev"],
    "ISO_27001": ["iso 27001", "27001"],
    "MDCG": ["mdcg"],
}

_THEME_ALIASES: Dict[str, List[str]] = {
    "clinical": [
        "clinical evaluation",
        "avaliação clínica",
        "avaliacao clinica",
        "cer ",
        "clinical data",
        "dados clínicos",
        "evidência clínica",
        "evidencia clinica",
    ],
    "software": [
        "software",
        "sdlc",
        "arquitetura de software",
        "srs",
        "código",
        "codigo",
        "soup",
        "software architecture",
        "software requirements",
    ],
    "ai": [
        "inteligência artificial",
        "inteligencia artificial",
        "ai model",
        "modelo de ia",
        "modelo ia",
        "machine learning",
        "deep learning",
        "llm",
        "ai governance",
        "ai transparency",
        "ia",
        "ai",
    ],
    "risk": [
        "risk management",
        "gestão de risco",
        "gestao de risco",
        "hazard",
        "fmea",
        "iso 14971",
        "risco residual",
        "matriz de risco",
    ],
    "cybersecurity": [
        "cybersecurity",
        "cibersegurança",
        "ciberseguranca",
        "vulnerabilities",
        "threat model",
        "sbom",
        "secure update",
        "penetration test",
    ],
    "usability": [
        "usability",
        "usabilidade",
        "human factors",
        "fatores humanos",
        "use error",
        "iec 62366",
        "summative",
        "formative",
    ],
    "qms": [
        "qms",
        "sistema da qualidade",
        "iso 13485",
        "controlo de documentos",
    ],
    "pms": [
        "post-market surveillance",
        "vigilância pós-mercado",
        "vigilancia pos-mercado",
        "pms",
        "psur",
    ],
    "pmcf": [
        "pmcf",
        "post-market clinical follow-up",
        "seguimento clínico pós-mercado",
        "seguimento clinico pos-mercado",
    ],
    "vigilance": [
        "vigilance",
        "vigilância",
        "vigilancia",
        "incident report",
        "fsca",
        "field safety",
        "fsn",
    ],
    "change_control": [
        "change control",
        "gestão de alterações",
        "gestao de alteracoes",
        "change request",
    ],
    "capa": [
        "capa",
        "corrective action",
        "preventive action",
        "ação corretiva",
        "acao corretiva",
        "root cause",
    ],
    "verification": ["verification", "verificação", "verificacao", "test protocol"],
    "validation": ["validation", "validação", "validacao"],
    "design_controls": [
        "design controls",
        "controlos de design",
        "design review",
        "stakeholder requirements",
    ],
}


# ---------------------------------------------------------------------------
# Construção de contexto a partir do histórico
# ---------------------------------------------------------------------------
def _msg_content(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content") or "")
    return str(getattr(msg, "content", "") or "")


def _msg_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role") or "").lower()
    return str(getattr(msg, "role", "") or "").lower()


def build_conversation_context(
    question: str,
    history: Optional[List[Any]] = None,
    *,
    max_user_messages: int = 6,
    max_chars: int = 2000,
) -> str:
    """Concatena a pergunta atual + últimas mensagens do utilizador no
    histórico para formar a query semântica do retrieval de templates."""
    parts: List[str] = []

    current = (question or "").strip()
    if current:
        parts.append(current)

    if history:
        recent_user_msgs: List[str] = []
        for msg in reversed(history):
            if _msg_role(msg) != "user":
                continue
            content = _msg_content(msg).strip()
            if not content or content == current:
                continue
            recent_user_msgs.append(content)
            if len(recent_user_msgs) >= max_user_messages:
                break
        parts.extend(reversed(recent_user_msgs))

    joined = "\n".join(parts)
    if len(joined) > max_chars:
        joined = joined[-max_chars:]
    return joined


# ---------------------------------------------------------------------------
# Deteção explícita de regulamentos e temas
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _alias_pattern(alias: str) -> re.Pattern:
    """Constrói uma regex com word-boundaries que respeita aliases curtos
    (ex: "ai", "ia") sem fazer match dentro de palavras (ex: "criar", "pai")."""
    return re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", re.IGNORECASE)


def _detect_from_aliases(text: str, aliases: Dict[str, List[str]]) -> List[str]:
    if not text:
        return []
    norm = _normalize(text)
    found: List[str] = []
    for canonical, variants in aliases.items():
        for v in variants:
            if _alias_pattern(v).search(norm):
                found.append(canonical)
                break
    return found


def detect_regulations(text: str) -> List[str]:
    """Devolve a lista de tags de regulamento mencionadas explicitamente."""
    return _detect_from_aliases(text, _REGULATION_ALIASES)


def detect_themes(text: str) -> List[str]:
    """Devolve a lista de temas regulatórios mencionados explicitamente."""
    return _detect_from_aliases(text, _THEME_ALIASES)


# ---------------------------------------------------------------------------
# Geração de rationale por sugestão
# ---------------------------------------------------------------------------
def _intersect(a: Iterable[str], b: Iterable[str]) -> List[str]:
    a_lower = {str(x).strip().lower(): str(x) for x in a if str(x).strip()}
    seen: Set[str] = set()
    out: List[str] = []
    for item in b:
        key = str(item).strip().lower()
        if key in a_lower and key not in seen:
            out.append(a_lower[key])
            seen.add(key)
    return out


def _build_rationale(
    record: TemplateRecord,
    matched_regulations: List[str],
    matched_themes: List[str],
    semantic_score: Optional[float],
) -> str:
    bits: List[str] = []
    if matched_regulations:
        bits.append("mencionaste " + ", ".join(matched_regulations))
    if matched_themes:
        bits.append("falaste sobre " + ", ".join(matched_themes))

    # Só falamos da semelhança semântica quando não há nada explícito; e mesmo
    # assim em linguagem qualitativa, nunca com o número cru (que pode ser
    # negativo se a distância no ChromaDB for >1).
    if not bits and semantic_score is not None:
        clamped = max(0.0, min(1.0, float(semantic_score)))
        if clamped >= 0.6:
            bits.append("relacionado com o tema da conversa")
        elif clamped >= 0.3:
            bits.append("tangencialmente relacionado com a conversa")

    if not bits:
        return f"{record.name} pode ser relevante para esta área regulatória."
    return f"Sugerido porque {' e '.join(bits)}."


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def suggest_templates(
    question: str,
    history: Optional[List[Any]] = None,
    *,
    n_results: int = 5,
    category: Optional[str] = None,
    regulation: Optional[str] = None,
    theme: Optional[str] = None,
) -> Dict[str, Any]:
    """Devolve sugestões contextuais para a conversa atual.

    Retorna:
        {
          "context_query": str,
          "detected_regulations": [...],
          "detected_themes": [...],
          "suggestions": [
            {
              "template": {... TemplateRecord.to_dict() ...},
              "score": float,
              "matched_regulations": [...],
              "matched_themes": [...],
              "prerequisites": [TemplateRecord.to_dict() ...],
              "rationale": str
            },
            ...
          ]
        }
    """
    context_query = build_conversation_context(question, history)
    if not context_query:
        return {
            "context_query": "",
            "detected_regulations": [],
            "detected_themes": [],
            "suggestions": [],
        }

    detected_regs = detect_regulations(context_query)
    detected_themes = detect_themes(context_query)

    raw_hits = search_templates(
        query=context_query,
        n_results=n_results,
        category=category,
        regulation=regulation,
        theme=theme,
    )

    suggestions: List[Dict[str, Any]] = []
    for hit in raw_hits:
        template_dict = hit["template"]
        try:
            record = get_record(template_dict["id"])
        except KeyError:
            continue

        matched_regs = _intersect(detected_regs, record.regulations)
        matched_themes_for_template = _intersect(detected_themes, record.themes)

        prerequisites: List[Dict[str, Any]] = []
        for dep_id in record.dependencies:
            try:
                prereq = get_record(dep_id)
            except KeyError:
                continue
            prerequisites.append(
                {
                    "id": prereq.id,
                    "name": prereq.name,
                    "category": prereq.category,
                }
            )

        suggestions.append(
            {
                "template": template_dict,
                "score": hit.get("score"),
                "matched_regulations": matched_regs,
                "matched_themes": matched_themes_for_template,
                "prerequisites": prerequisites,
                "rationale": _build_rationale(
                    record,
                    matched_regs,
                    matched_themes_for_template,
                    hit.get("score"),
                ),
            }
        )

    return {
        "context_query": context_query,
        "detected_regulations": detected_regs,
        "detected_themes": detected_themes,
        "suggestions": suggestions,
    }


def orchestrator_taxonomy() -> Dict[str, Any]:
    """Expõe a taxonomia conhecida (do registry) + os aliases que o
    orchestrator entende em linguagem natural — útil para debug e para o
    frontend mostrar o vocabulário suportado."""
    return {
        "registry_taxonomy": list_tags().get("taxonomy", {}),
        "regulation_aliases": _REGULATION_ALIASES,
        "theme_aliases": _THEME_ALIASES,
    }
