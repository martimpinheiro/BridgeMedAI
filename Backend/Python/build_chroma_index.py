from __future__ import annotations

import os
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from rag_chromadb_service import get_chroma_collection, chroma_reset_collection

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

EMBEDDINGS_PATH = (
    PROJECT_ROOT / os.getenv("EMBEDDINGS_PATH", "Backend/local_embeddings.pkl")
).resolve()


def load_pickle_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Ficheiro de embeddings não encontrado: {path}")

    with open(path, "rb") as fh:
        payload = pickle.load(fh)

    if not isinstance(payload, dict):
        raise ValueError("O ficheiro .pkl não contém um dicionário válido.")

    if "records" not in payload:
        raise ValueError("O ficheiro .pkl não contém a chave 'records'.")

    if "embeddings" not in payload:
        raise ValueError("O ficheiro .pkl não contém a chave 'embeddings'.")

    return payload


def get_record_text(record: Dict[str, Any]) -> str:
    """
    O payload antigo usa sobretudo 'chunk_text'.
    Algumas versões podem usar 'text'.
    Esta função garante que nunca indexamos documentos vazios por engano.
    """
    text = (
        record.get("chunk_text")
        or record.get("text")
        or record.get("raw_text")
        or ""
    )
    return str(text).strip()


def infer_section_type(record: Dict[str, Any]) -> str:
    """
    Corrige o tipo da fonte antes de indexar no Chroma.

    O payload antigo pode guardar section_type='chapter' ou 'annex' mesmo quando
    o texto real começa por uma regra do Anexo VIII, por exemplo:
    'Regra n.o 10 ...'

    Também deteta pontos como:
    '5. Classe de risco do dispositivo...'
    quando a citation_label já diz 'Ponto 5'.
    """
    original_type = str(record.get("section_type", "") or "").strip().lower()

    citation = str(record.get("citation_label", "") or "")
    section_number = str(record.get("section_number", "") or "")
    section_title = str(record.get("section_title", "") or "")
    chunk_text = (
        record.get("chunk_text")
        or record.get("text")
        or record.get("raw_text")
        or ""
    )

    combined = f"{citation} {section_number} {section_title} {chunk_text}"
    combined_norm = combined.lower()

    # Casos normais: "Regra 1", "Regra 10"
    if re.search(r"\bregra\s+\d+\b", combined_norm):
        return "rule"

    # Casos do PDF português: "Regra n.o 10", "Regra n.º 10", "Regra no 10"
    if re.search(r"\bregra\s+n\.?\s*[ºo°]?\s*\d+\b", combined_norm):
        return "rule"

    # Casos com "Rule 10"
    if re.search(r"\brule\s+\d+\b", combined_norm):
        return "rule"

    # Pontos explícitos na citação
    if re.search(r"\bponto\s+\d+\b", combined_norm):
        return "point"

    return original_type


def infer_section_number(record: Dict[str, Any]) -> str:
    """
    Extrai uma secção mais específica quando o texto/citação contém Regra ou Ponto.

    Exemplos:
    - 'Regra n.o 10 Os dispositivos ativos...' -> 'Regra 10'
    - 'MDR ANEXO IV Ponto 5' -> 'Ponto 5'
    """
    citation = str(record.get("citation_label", "") or "")
    section_number = str(record.get("section_number", "") or "")
    chunk_text = (
        record.get("chunk_text")
        or record.get("text")
        or record.get("raw_text")
        or ""
    )

    combined = f"{citation} {section_number} {chunk_text}"

    m_rule_normal = re.search(
        r"\bRegra\s+(\d+)\b",
        combined,
        flags=re.IGNORECASE,
    )
    if m_rule_normal:
        return f"Regra {m_rule_normal.group(1)}"

    m_rule_no = re.search(
        r"\bRegra\s+n\.?\s*[ºo°]?\s*(\d+)\b",
        combined,
        flags=re.IGNORECASE,
    )
    if m_rule_no:
        return f"Regra {m_rule_no.group(1)}"

    m_rule_en = re.search(
        r"\bRule\s+(\d+)\b",
        combined,
        flags=re.IGNORECASE,
    )
    if m_rule_en:
        return f"Regra {m_rule_en.group(1)}"

    m_point = re.search(
        r"\bPonto\s+(\d+)\b",
        combined,
        flags=re.IGNORECASE,
    )
    if m_point:
        return f"Ponto {m_point.group(1)}"

    return section_number



def infer_citation_label(record: Dict[str, Any]) -> str:
    """
    Cria citações mais específicas antes de indexar no Chroma.

    Principal correção:
    - O payload antigo guarda regras do Anexo VIII como "MDR CAPÍTULO III".
    - Para o chatbot, é muito melhor citar como "MDR ANEXO VIII Regra 1",
      "MDR ANEXO VIII Regra 10", etc.
    """
    original_citation = str(record.get("citation_label", "") or "").strip()
    short_name = str(record.get("short_name", "") or "").strip()
    section_title = str(record.get("section_title", "") or "").strip().lower()

    inferred_type = infer_section_type(record)
    inferred_number = infer_section_number(record)

    if short_name == "MDR" and inferred_type == "rule":
        if (
            "regras de classificação" in section_title
            or "regras de classificacao" in section_title
            or "capítulo iii" in original_citation.lower()
            or "capitulo iii" in original_citation.lower()
        ):
            return f"MDR ANEXO VIII {inferred_number}"

    if short_name == "MDR" and inferred_type == "point":
        if "declaração ue de conformidade" in section_title or "declaracao ue de conformidade" in section_title:
            return f"MDR ANEXO IV {inferred_number}"

        if "registo de dispositivos" in section_title or "operadores" in section_title:
            return f"MDR ANEXO VI {inferred_number}"

    return original_citation


def build_document_text(record: Dict[str, Any]) -> str:
    chunk_text = get_record_text(record)

    parts = [
        f"Citação: {infer_citation_label(record)}",
        f"Documento: {record.get('short_name', '')}",
        f"Tipo: {infer_section_type(record)}",
        f"Secção: {infer_section_number(record)}",
        f"Título: {record.get('section_title', '')}",
        f"Páginas: {record.get('page_start', '')} - {record.get('page_end', '')}",
        "",
        "Texto:",
        chunk_text,
    ]

    return "\n".join(parts).strip()


def safe_int(value: Any) -> int:
    try:
        if value in (None, "", -1, "-1"):
            return -1
        return int(value)
    except Exception:
        return -1


def record_metadata(record: Dict[str, Any]) -> Dict[str, Any]:
    chunk_id = record.get("chunk_id", "")

    return {
        "chunk_id": str(chunk_id)[:100],
        "citation_label": infer_citation_label(record)[:500],
        "short_name": str(record.get("short_name", ""))[:200],
        "section_type": infer_section_type(record)[:100],
        "section_number": infer_section_number(record)[:200],
        "section_title": str(record.get("section_title", ""))[:500],
        "page_start": safe_int(record.get("page_start")),
        "page_end": safe_int(record.get("page_end")),
        "has_text": bool(get_record_text(record)),
    }


def normalize_embeddings(raw_embeddings: Any) -> List[List[float]]:
    if raw_embeddings is None:
        raise ValueError("A chave 'embeddings' está vazia no ficheiro .pkl.")

    normalized: List[List[float]] = []

    for emb in raw_embeddings:
        if hasattr(emb, "tolist"):
            emb = emb.tolist()

        if not isinstance(emb, list):
            raise ValueError("Foi encontrado um embedding num formato inválido.")

        normalized.append([float(x) for x in emb])

    return normalized


def main() -> None:
    payload = load_pickle_payload(EMBEDDINGS_PATH)
    records = payload["records"]
    embeddings = normalize_embeddings(payload["embeddings"])

    if not isinstance(records, list) or not records:
        raise ValueError("Não existem records válidos para indexar.")

    if len(records) != len(embeddings):
        raise ValueError(
            f"Número de records ({len(records)}) diferente do número de embeddings ({len(embeddings)})."
        )

    empty_text_count = sum(1 for r in records if not get_record_text(r))
    rule_count = sum(1 for r in records if infer_section_type(r) == "rule")
    point_count = sum(1 for r in records if infer_section_type(r) == "point")

    print(f"[Chroma] Records no payload: {len(records)}")
    print(f"[Chroma] Records sem texto: {empty_text_count}")
    print(f"[Chroma] Rules inferidas: {rule_count}")
    print(f"[Chroma] Points inferidos: {point_count}")

    if empty_text_count == len(records):
        raise ValueError(
            "Todos os records estão sem texto. O problema está no ficheiro local_embeddings.pkl. "
            "É necessário regenerar o .pkl antes de indexar no Chroma."
        )

    print("[Chroma] A limpar coleção anterior...")
    chroma_reset_collection()
    collection = get_chroma_collection()

    batch_size = 64
    total = len(records)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch_records = records[start:end]
        batch_embeddings = embeddings[start:end]

        ids = [f"doc_{i}" for i in range(start, end)]
        documents = [build_document_text(r) for r in batch_records]
        metadatas = [record_metadata(r) for r in batch_records]

        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=batch_embeddings,
        )

        print(f"[Chroma] Indexados {end}/{total}")

    print("[Chroma] Indexação concluída com sucesso.")
    print("[Chroma] Count final:", collection.count())


if __name__ == "__main__":
    main()