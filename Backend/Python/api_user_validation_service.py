from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
VALIDATION_CASES_PATH = PROJECT_ROOT / "Backend" / "validation_cases" / "mdr_ai_validation_cases.json"


def _normalize(text: Any) -> str:
    text = str(text or "").lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def _load_cases() -> List[Dict[str, Any]]:
    if not VALIDATION_CASES_PATH.exists():
        return []

    with open(VALIDATION_CASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data if isinstance(data, list) else []


def _tokens(text: str) -> set[str]:
    text = _normalize(text)
    return {t for t in re.findall(r"[a-z0-9_]+", text) if len(t) >= 3}


def _term_hits(text: str, terms: List[str]) -> int:
    text_norm = _normalize(text)
    hits = 0

    for term in terms or []:
        term_norm = _normalize(term)
        if term_norm and term_norm in text_norm:
            hits += 1

    return hits


def _contains_any(text: str, terms: List[str]) -> bool:
    return _term_hits(text, terms) > 0


def _case_match_score(question: str, answer: str, case: Dict[str, Any]) -> float:
    """
    Score de matching entre pergunta/resposta e caso de referência.

    Regra importante:
    - a pergunta pesa muito mais do que a resposta;
    - negative_keywords penalizam casos demasiado genéricos;
    - required_keywords_any impede que casos específicos sejam escolhidos
      quando faltam sinais essenciais;
    - boost_keywords ajudam a distinguir famílias parecidas.
    """
    q = _normalize(question)
    a = _normalize(answer)

    keywords = case.get("keywords") or []
    negative_keywords = case.get("negative_keywords") or []
    required_any = case.get("required_keywords_any") or []
    boost_keywords = case.get("boost_keywords") or []

    if not keywords:
        return 0.0

    q_hits = _term_hits(q, keywords)
    a_hits = _term_hits(a, keywords)

    # A pergunta manda. A resposta só ajuda ligeiramente.
    keyword_score = (q_hits + 0.20 * a_hits) / max(1, len(keywords))

    title_tokens = _tokens(case.get("title", ""))
    q_tokens = _tokens(q)
    overlap_score = len(title_tokens & q_tokens) / max(1, len(title_tokens))

    boost_hits = _term_hits(q, boost_keywords)
    boost_score = min(0.18, 0.06 * boost_hits)

    negative_hits = _term_hits(q, negative_keywords)
    negative_penalty = min(0.45, 0.14 * negative_hits)

    score = (0.72 * keyword_score) + (0.18 * overlap_score) + boost_score - negative_penalty

    # Se o caso exige pelo menos um termo específico e a pergunta não tem nenhum,
    # despromove fortemente. Ex.: caso com IA sem "IA" nem "algoritmo".
    if required_any and not _contains_any(q, required_any):
        score *= 0.25

    # Se há muitas keywords negativas, evita escolher o caso mesmo que tenha
    # palavras genéricas em comum. Ex.: termómetro simples vs termómetro IA.
    if negative_hits >= 2:
        score = min(score, 0.18)

    return round(max(0.0, min(1.0, score)), 4)


def _best_case(question: str, answer: str, min_score: float = 0.22) -> Tuple[Optional[Dict[str, Any]], float]:
    cases = _load_cases()
    best = None
    best_score = 0.0

    for case in cases:
        score = _case_match_score(question, answer, case)
        if score > best_score:
            best = case
            best_score = score

    if not best or best_score < min_score:
        return None, best_score

    return best, best_score


def _extract_answer_classes(answer: str) -> List[str]:
    text = _normalize(answer)
    found: List[str] = []

    # Ordem importante para não detetar I dentro de IIa/IIb/III.
    patterns = [
        ("III", r"\bclasse\s+iii\b"),
        ("IIb", r"\bclasse\s+iib\b"),
        ("IIa", r"\bclasse\s+iia\b"),
        ("I", r"\bclasse\s+i\b"),
    ]

    for cls, pattern in patterns:
        if re.search(pattern, text):
            found.append(cls)

    return found


def _used_sources_text(entry: Dict[str, Any]) -> str:
    """
    Texto usado para validar citações.

    Importante:
    - usa apenas answer + generation_sources;
    - NÃO usa retrieved_sources, porque essas fontes podem ter sido apenas
      consultadas e não usadas na geração.
    """
    parts: List[str] = []

    sources = entry.get("generation_sources") or []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict):
                parts.append(str(s.get("citation_label", "")))
                parts.append(str(s.get("section_number", "")))
                parts.append(str(s.get("section_title", "")))

    parts.append(str(entry.get("answer", "")))

    return _normalize(" ".join(parts))


def _citation_present(expected_citation: Optional[str], entry: Dict[str, Any]) -> Optional[bool]:
    if not expected_citation:
        return None

    expected_norm = _normalize(expected_citation)
    text = _used_sources_text(entry)

    if expected_norm in text:
        return True

    # Fallback controlado: se esperamos "Regra 10", aceitar apenas se a resposta
    # ou fonte usada mencionar Regra 10 de forma clara. Não aceita Artigo 123/51.
    m = re.search(r"regra\s+(\d+)", expected_norm)
    if m:
        rule = f"regra {m.group(1)}"
        if rule in text and ("anexo viii" in text or "classificacao" in text or "classificação" in text):
            return True

    # Fallback para Artigos.
    m = re.search(r"artigo\s+(\d+)", expected_norm)
    if m:
        article = f"artigo {m.group(1)}"
        if article in text:
            if "ai_act" in expected_norm or "ai act" in expected_norm:
                return "ai_act" in text or "ai act" in text or "2024/1689" in text
            return True

    return False


def _ai_act_present(entry: Dict[str, Any]) -> bool:
    text = _used_sources_text(entry)
    return (
        "ai_act" in text
        or "ai act" in text
        or "2024/1689" in text
        or ("artigo 6" in text and ("ia" in text or "inteligencia artificial" in text))
    )


def _medical_device_scope_ok(expected: Dict[str, Any], answer: str) -> Optional[bool]:
    expected_value = expected.get("mdr_is_medical_device")
    if expected_value is None:
        return None

    text = _normalize(answer)

    negative_signals = [
        "nao e dispositivo medico",
        "nao e um dispositivo medico",
        "não é dispositivo médico",
        "não é um dispositivo médico",
        "fora do mdr",
        "nao se enquadra como dispositivo medico",
        "não se enquadra como dispositivo médico",
    ]

    positive_signals = [
        "dispositivo medico",
        "dispositivo médico",
        "finalidade medica",
        "finalidade médica",
        "diagnostico",
        "diagnóstico",
        "monitorizacao",
        "monitorização",
    ]

    says_negative = any(_normalize(s) in text for s in negative_signals)
    says_positive = any(_normalize(s) in text for s in positive_signals)

    if expected_value is True:
        return says_positive and not says_negative

    if expected_value is False:
        return says_negative or "sem finalidade medica" in text or "sem finalidade médica" in text

    return None


def validate_traceability_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    question = entry.get("question") or ""
    answer = entry.get("answer") or ""

    if not question and not answer:
        return {
            "status": "NO_CASE",
            "status_label": "Sem conteúdo para validar",
            "case": None,
            "match_score": 0.0,
            "checks": [],
            "recommendation": "Esta entrada não tem pergunta/resposta suficiente para validação automática.",
        }

    case, match_score = _best_case(question, answer)

    if not case:
        return {
            "status": "NO_CASE",
            "status_label": "Sem caso de referência",
            "case": None,
            "match_score": match_score,
            "checks": [],
            "recommendation": "Não há ainda um caso de teste suficientemente parecido. Pode enviar ao especialista se quiser revisão manual.",
        }

    expected = case.get("expected") or {}
    answer_classes = _extract_answer_classes(answer)
    expected_class = expected.get("mdr_class")
    allowed_classes = case.get("allowed_classes") or ([expected_class] if expected_class else [])

    checks: List[Dict[str, Any]] = []

    if expected_class:
        class_ok = any(cls in allowed_classes for cls in answer_classes)
        checks.append({
            "key": "mdr_class",
            "label": "Classe MDR",
            "expected": expected_class,
            "observed": ", ".join(answer_classes) if answer_classes else "não detetada",
            "ok": class_ok,
        })

    expected_rule = expected.get("mdr_rule")
    citation_ok = _citation_present(expected_rule, entry)
    if citation_ok is not None:
        checks.append({
            "key": "mdr_rule",
            "label": "Regra/citação MDR usada",
            "expected": expected_rule,
            "observed": "usada na resposta/fontes de geração" if citation_ok else "não detetada nas fontes usadas",
            "ok": citation_ok,
        })

    ai_expected = bool(expected.get("ai_act_relevant"))
    ai_observed = _ai_act_present(entry)
    checks.append({
        "key": "ai_act",
        "label": "AI Act mencionado",
        "expected": "mencionado" if ai_expected else "não obrigatório",
        "observed": "mencionado" if ai_observed else "não mencionado",
        "ok": ai_observed if ai_expected else True,
    })

    ai_reference = expected.get("ai_act_reference")
    ai_reference_ok = _citation_present(ai_reference, entry)
    if ai_reference_ok is not None:
        checks.append({
            "key": "ai_act_reference",
            "label": "Fonte AI Act usada",
            "expected": ai_reference,
            "observed": "usada na resposta/fontes de geração" if ai_reference_ok else "não detetada nas fontes usadas",
            "ok": ai_reference_ok,
        })

    scope_ok = _medical_device_scope_ok(expected, answer)
    if scope_ok is not None:
        checks.append({
            "key": "medical_device_scope",
            "label": "Qualificação como dispositivo médico",
            "expected": "sim" if expected.get("mdr_is_medical_device") else "não/fora MDR provável",
            "observed": "compatível" if scope_ok else "potencialmente incompatível",
            "ok": scope_ok,
        })

    must_mentions = case.get("must_mention") or []
    answer_norm = _normalize(answer)
    missing_mentions = [m for m in must_mentions if _normalize(m) not in answer_norm]
    if must_mentions:
        checks.append({
            "key": "must_mention",
            "label": "Elementos que deviam aparecer",
            "expected": ", ".join(must_mentions),
            "observed": "em falta: " + ", ".join(missing_mentions) if missing_mentions else "presentes",
            "ok": len(missing_mentions) == 0,
        })

    ok_count = sum(1 for c in checks if c.get("ok") is True)
    fail_count = sum(1 for c in checks if c.get("ok") is False)

    if fail_count == 0:
        status = "OK"
        label = "Parece consistente"
        recommendation = "A resposta parece alinhada com o caso de referência. Ainda assim, pode enviar ao especialista para validação formal."
    elif ok_count > 0:
        status = "PARCIAL"
        label = "Parcialmente consistente"
        recommendation = "Há pontos consistentes, mas também lacunas. Recomenda-se revisão antes de usar a resposta."
    else:
        status = "NOK"
        label = "Possível erro"
        recommendation = "A resposta parece desalinhada com o caso de referência. Recomenda-se enviar ao especialista."

    return {
        "status": status,
        "status_label": label,
        "case": {
            "case_id": case.get("case_id"),
            "title": case.get("title"),
            "device_family": case.get("device_family"),
        },
        "match_score": match_score,
        "checks": checks,
        "recommendation": recommendation,
    }


def build_user_validation_matrix(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    for entry in entries:
        enriched = dict(entry)
        enriched["auto_validation"] = validate_traceability_entry(entry)
        out.append(enriched)

    return out