"""
Extrator de placeholders `<...>` reais nos templates Fraunhofer.

Os templates Fraunhofer usam marcadores no formato `<descrição/instrução>`
nas zonas que o autor humano deve preencher (nome do produto, versão, etc.).
Este módulo:

1. Abre o .docx
2. Encontra todos os `<...>` em paragraphs (incluindo dentro de tabelas
   e header/footer)
3. Devolve uma lista ordenada de placeholders com texto + contexto + chave
   estável (hash) — para serem perguntados em chat e depois substituídos

Não é tentativa de "ler entre linhas" das instruções italic/amarelas dos
templates. Essas continuam por preencher manualmente — é por design dos
Fraunhofer (cada secção tem orientação para o autor humano).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from docx import Document

# Captura <texto> com no máximo 500 chars internos, sem `<` ou `>` aninhados.
# Permite quebras de linha (Word às vezes parte texto longo em runs).
_PLACEHOLDER_RE = re.compile(r"<([^<>]{1,500})>", re.DOTALL)


@dataclass(frozen=True)
class Placeholder:
    """Um marcador `<...>` encontrado num template Fraunhofer."""

    key: str            # hash curto para identificação estável
    raw_text: str       # texto exato dentro de `<>` (sem os angle brackets)
    full_match: str     # com angle brackets, para substituição: "<...>"
    context: str        # cabeçalho/secção próxima — ajuda a perceber o que pedir
    location: str       # ex: "body", "t2r1c0", "header"
    order: int          # ordem em que aparece no documento

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "raw_text": self.raw_text,
            "full_match": self.full_match,
            "context": self.context,
            "location": self.location,
            "order": self.order,
        }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _make_key(raw_text: str, location: str) -> str:
    """Chave estável para o placeholder. Inclui location para distinguir
    placeholders idênticos em sítios diferentes (raro mas possível)."""
    h = hashlib.sha1(f"{location}::{_normalize(raw_text).lower()}".encode("utf-8")).hexdigest()
    return h[:10]


def _placeholders_in_text(
    text: str,
    location: str,
    context: str,
    start_order: int,
) -> List[Placeholder]:
    out: List[Placeholder] = []
    if not text or "<" not in text:
        return out
    for i, match in enumerate(_PLACEHOLDER_RE.finditer(text)):
        raw_inner = match.group(1)
        normalized_inner = _normalize(raw_inner)
        # Filtra falsos positivos óbvios (tags HTML/XML que escaparam, datas
        # tipo <1, comparadores). Heurística: aceitar se tiver pelo menos
        # uma letra alfabética.
        if not re.search(r"[A-Za-zÀ-ÿ]", normalized_inner):
            continue
        # Filtra também tags de markup conhecidas
        if normalized_inner.lower() in {"br", "hr", "p", "b", "i", "u"}:
            continue
        full = f"<{raw_inner}>"
        loc_with_idx = f"{location}#{i}" if i else location
        out.append(
            Placeholder(
                key=_make_key(raw_inner, loc_with_idx),
                raw_text=normalized_inner,
                full_match=full,
                context=context,
                location=loc_with_idx,
                order=start_order + i,
            )
        )
    return out


def _nearest_heading_for_paragraph(
    paragraphs: List[Any],
    index: int,
    max_lookback: int = 10,
) -> str:
    """Procura para trás até `max_lookback` parágrafos por algo que pareça
    cabeçalho (estilo Heading X ou texto curto e isolado)."""
    for back in range(index - 1, max(-1, index - max_lookback), -1):
        p = paragraphs[back]
        style = getattr(getattr(p, "style", None), "name", "") or ""
        if "Heading" in style or "Title" in style:
            return _normalize(p.text)
        # heurística: parágrafo curto não-vazio sem ponto final
        txt = _normalize(p.text)
        if 3 < len(txt) < 80 and not txt.endswith(".") and not txt.endswith(":"):
            # provável cabeçalho informal
            return txt
    return ""


def extract_placeholders(template_path: Path) -> List[Placeholder]:
    """Devolve todos os placeholders `<...>` do template, com contexto."""
    doc = Document(str(template_path))
    out: List[Placeholder] = []
    order = 0

    # 1) Parágrafos do body com contexto = cabeçalho mais próximo
    paragraphs = list(doc.paragraphs)
    for pi, p in enumerate(paragraphs):
        ctx = _nearest_heading_for_paragraph(paragraphs, pi)
        found = _placeholders_in_text(p.text, "body", ctx, order)
        out.extend(found)
        order += len(found)

    # 2) Tabelas: contexto = cabeçalho da coluna (primeira linha) se existir
    for ti, table in enumerate(doc.tables):
        header_row = table.rows[0] if table.rows else None
        col_headers: List[str] = []
        if header_row:
            for cell in header_row.cells:
                txt = ""
                if cell.paragraphs:
                    txt = _normalize(cell.paragraphs[0].text)
                col_headers.append(txt)

        for ri, row in enumerate(table.rows):
            if ri == 0 and header_row is not None:
                # Saltamos a header row (não costuma ter placeholders relevantes)
                # mas processamos caso o user tenha posto algo lá
                pass
            for ci, cell in enumerate(row.cells):
                col_header = col_headers[ci] if ci < len(col_headers) else ""
                for p in cell.paragraphs:
                    loc = f"t{ti}r{ri}c{ci}"
                    ctx = col_header or f"tabela {ti}"
                    found = _placeholders_in_text(p.text, loc, ctx, order)
                    out.extend(found)
                    order += len(found)

    # 3) Header / footer
    for sec_i, sec in enumerate(doc.sections):
        for hf_label, hf in [("header", sec.header), ("footer", sec.footer)]:
            if hf is None:
                continue
            for p in hf.paragraphs:
                loc = f"{hf_label}{sec_i}"
                found = _placeholders_in_text(p.text, loc, hf_label, order)
                out.extend(found)
                order += len(found)
            for ti, t in enumerate(hf.tables):
                for ri, row in enumerate(t.rows):
                    for ci, cell in enumerate(row.cells):
                        for p in cell.paragraphs:
                            loc = f"{hf_label}{sec_i}-t{ti}r{ri}c{ci}"
                            found = _placeholders_in_text(p.text, loc, hf_label, order)
                            out.extend(found)
                            order += len(found)

    # Dedup mantendo a primeira ocorrência (chaves iguais = pergunta única)
    seen: Set[str] = set()
    deduped: List[Placeholder] = []
    for ph in out:
        if ph.key in seen:
            continue
        seen.add(ph.key)
        deduped.append(ph)

    # Ordenar por ordem de aparecimento
    deduped.sort(key=lambda p: p.order)
    return deduped


# ---------------------------------------------------------------------------
# Construção de perguntas em PT para um placeholder
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Mapeamentos PT — placeholder Fraunhofer → pergunta semântica
# ---------------------------------------------------------------------------
# Estratégia em camadas:
#   1) match exato (case-insensitive) — para os placeholders comuns
#   2) match por palavras-chave dentro do texto (substring)
#   3) heurística baseada na primeira frase / palavras estruturais
# Em todas as camadas a CHAVE de substituição permanece o `<...>` original;
# só a PERGUNTA que mostramos ao user é que muda.

# Mapeamentos exatos — chave normalizada (lowercase, espaços colapsados,
# sem ponto final). Cobre os placeholders que vimos nos 36 templates.
_EXACT_MAP = {
    # Identificação do produto
    "name of the product": "Qual é o nome do produto?",
    "version of the product": "Qual é a versão do produto?",
    "version of the software": "Qual é a versão do software?",
    "basic udi-di, if/when available": "Qual é o Basic UDI-DI (se já tens)?",
    "company": "Qual é o nome da empresa/fabricante?",

    # Versionamento / autoria
    "name": "Qual é o teu nome (para ficar registado)?",
    "date": "Que data devo colocar? (AAAA-MM-DD)",
    "author": "Quem é o autor deste documento?",
    "approved by": "Quem aprova este documento?",
    "created by": "Quem criou este documento?",
    "description of change": "Resume a alteração principal desta versão.",
    "version": "Qual é o número da versão? (ex: 1.0)",

    # Clínico
    "intended purpose": "Qual é a finalidade prevista do dispositivo?",
    "intended use": "Para que serve o dispositivo? (uso pretendido)",
    "indication": "Quais são as indicações de uso?",
    "indications": "Quais são as indicações de uso?",
    "contraindication": "Há contraindicações?",
    "contraindications": "Há contraindicações?",
    "target population": "Qual é a população-alvo do dispositivo?",
    "patient population": "Qual é a população de doentes?",
    "intended users": "Quem são os utilizadores-alvo?",
    "user profile": "Descreve o perfil dos utilizadores.",
    "clinical benefit": "Quais são os benefícios clínicos esperados?",
    "clinical benefits": "Quais são os benefícios clínicos esperados?",

    # Risco
    "hazard": "Que perigo (hazard) estás a descrever?",
    "harm": "Qual é o dano potencial?",
    "severity": "Qual a severidade estimada?",
    "probability": "Qual a probabilidade estimada?",
    "risk control measure": "Descreve a medida de controlo de risco.",
    "residual risk": "Qual é o risco residual após as medidas?",

    # Software / IA
    "software item": "Descreve o item de software.",
    "software unit": "Descreve a unidade de software.",
    "soup name": "Qual é o nome do componente SOUP/OTS?",
    "soup version": "Qual é a versão do componente SOUP/OTS?",
    "ai model": "Descreve o modelo de IA usado.",

    # Cibersegurança
    "threat": "Que ameaça de cibersegurança estás a descrever?",
    "vulnerability": "Qual é a vulnerabilidade?",
    "asset": "Qual é o ativo a proteger?",
}

# Tokens "qualificadores" que apenas indicam tipo de campo — mapeados
# directamente para a pergunta principal mesmo que sejam parte de placeholders
# mais longos (ex: 'version of the product. If standalone software...').
_KEYWORD_TRIGGERS = [
    ("version of the product", "Qual é a versão do produto?"),
    ("version of the software", "Qual é a versão do software?"),
    ("name of the product", "Qual é o nome do produto?"),
    ("basic udi-di", "Qual é o Basic UDI-DI?"),
    ("intended purpose", "Qual é a finalidade prevista do dispositivo?"),
    ("intended use", "Para que serve o dispositivo? (uso pretendido)"),
    ("target population", "Qual é a população-alvo?"),
    ("patient population", "Qual é a população de doentes?"),
    ("clinical benefit", "Quais são os benefícios clínicos esperados?"),
    ("residual risk", "Qual é o risco residual?"),
    ("description of change", "Resume a alteração principal."),
]


def _normalize_lookup(text: str) -> str:
    import re as _re
    s = _re.sub(r"\s+", " ", text or "").strip().lower()
    # tira pontuação final
    s = s.rstrip(".:,;")
    return s


def _first_sentence(text: str, max_len: int = 90) -> str:
    """Devolve a primeira frase do placeholder (até ao primeiro ponto ou
    vírgula) — útil para placeholders longos com instruções extra."""
    if not text:
        return ""
    import re as _re
    # corta no primeiro ponto/. , ;
    for sep in [". ", ".\n", "; ", ", If ", ", if ", " (e.g.", " (i.e."]:
        idx = text.find(sep)
        if idx > 0:
            return text[:idx].strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + "…"
    return text.strip()


def humanize_placeholder_text(raw_text: str) -> str:
    """Converte o texto cru de um placeholder Fraunhofer numa pergunta legível.

    Em todas as camadas a chave de substituição (`<placeholder>`) permanece —
    só muda a PERGUNTA mostrada ao user.
    """
    if not raw_text or not raw_text.strip():
        return "Indica o valor."

    norm = _normalize_lookup(raw_text)

    # 1) match exato
    if norm in _EXACT_MAP:
        return _EXACT_MAP[norm]

    # 2) match por palavras-chave (substring) — apanha placeholders longos
    for keyword, question in _KEYWORD_TRIGGERS:
        if keyword in norm:
            return question

    # 3) heurística por palavras estruturais
    first = _first_sentence(raw_text)
    first_lc = first.lower()

    if first_lc.startswith("enter "):
        # 'enter number between 0 and 3' → 'Indica um número entre 0 e 3.'
        rest = first[6:].strip()
        # traduções simples
        rest = (rest
            .replace("number between", "um número entre")
            .replace("date", "uma data")
            .replace("text", "um texto")
            .replace(" and ", " e ")
        )
        return f"Indica {rest}."

    if first_lc.startswith("describe ") or first_lc.startswith("description"):
        rest = first.split(" ", 1)[1] if " " in first else first
        return f"Descreve {rest.lower()}."

    if "version" in norm:
        return f"Qual é a versão? (referência no template: «{first}»)"
    if "name of " in norm or norm.startswith("name "):
        return f"Qual é o nome? (referência no template: «{first}»)"
    if "date" in norm:
        return f"Que data devo colocar? (AAAA-MM-DD) — campo: «{first}»"
    if norm.startswith("if "):
        # 'if standalone software, use...' — não é placeholder real útil
        return f"Indica o valor para: «{first}»"

    # fallback: usa a primeira frase mas com framing de pergunta
    return f"Indica: {first}"
