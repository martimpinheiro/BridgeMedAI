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
def humanize_placeholder_text(raw_text: str) -> str:
    """Converte o texto cru de um placeholder Fraunhofer numa pergunta legível.

    A maioria dos Fraunhofer está em inglês ('name of the product', 'version of
    the software'). Mapeamos os mais comuns para PT; o resto fica no original
    (que costuma ser claro)."""
    t = raw_text.strip().lower()
    # mapeamentos exatos comuns
    direct = {
        "name of the product": "Qual é o nome do produto?",
        "version of the product": "Qual é a versão do produto?",
        "version of the software": "Qual é a versão do software?",
        "basic udi-di, if/when available": "Qual é o Basic UDI-DI? (deixa em branco se ainda não tens)",
        "company": "Qual é o nome da empresa/fabricante?",
        "name": "Qual é o nome?",
        "date": "Que data devo colocar? (YYYY-MM-DD)",
        "author": "Quem é o autor?",
        "approved by": "Quem aprovou?",
        "created by": "Quem criou?",
        "description of change": "Qual é a descrição da alteração?",
        "version": "Qual é a versão?",
    }
    if t in direct:
        return direct[t]
    # heurística genérica
    if " of the " in t or "name" in t or "version" in t or "date" in t:
        return f"Qual é o(a) {raw_text.strip()}?"
    return f"Indica: {raw_text.strip()}"
