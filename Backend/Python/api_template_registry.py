"""
Template Registry do BridgeMedAI.

Camada de catálogo dos templates regulatórios (Backend/templates/registry.json)
usada pelo Regulatory Documentation Copilot:

- carrega e valida a metadata canónica do registry;
- expõe operações puras de listagem, filtragem e obtenção de templates;
- resolve o caminho físico do ficheiro .docx/.xlsx no disco;
- mantém um índice semântico ChromaDB separado (collection
  `bridgemedai_templates`) reaproveitando o mesmo modelo de embeddings
  (Ollama) que o RAG regulatório, para permitir descoberta contextual
  de templates a partir de uma frase em linguagem natural.

Este módulo é aditivo: não altera nem depende da collection regulatória
existente (`bridgemedai_regulatory`).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from rag_chromadb_service import get_chroma_client
from api_rag_service import embed_query_text

# ---------------------------------------------------------------------------
# Localização do registry e dos ficheiros
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
TEMPLATES_DIR = (PROJECT_ROOT / "Backend" / "templates").resolve()
REGISTRY_PATH = TEMPLATES_DIR / "registry.json"

TEMPLATES_COLLECTION_NAME = os.getenv(
    "CHROMA_TEMPLATES_COLLECTION_NAME",
    "bridgemedai_templates",
)


# ---------------------------------------------------------------------------
# Carregamento do registry
# ---------------------------------------------------------------------------
class RegistryError(RuntimeError):
    """Erro ao carregar ou validar o registry de templates."""


@dataclass(frozen=True)
class TemplateRecord:
    """Representação imutável de uma entrada do registry."""

    id: str
    name: str
    file: str
    category: str
    doc_type: str
    description: str
    keywords: List[str]
    regulations: List[str]
    themes: List[str]
    mandatory_sections: List[str]
    optional_sections: List[str]
    auto_fillable_fields: List[str]
    human_required_fields: List[str]
    dependencies: List[str]
    feeds_into: List[str]
    workflow_priority: int
    metadata_status: str
    raw: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "file": self.file,
            "category": self.category,
            "doc_type": self.doc_type,
            "description": self.description,
            "keywords": list(self.keywords),
            "regulations": list(self.regulations),
            "themes": list(self.themes),
            "mandatory_sections": list(self.mandatory_sections),
            "optional_sections": list(self.optional_sections),
            "auto_fillable_fields": list(self.auto_fillable_fields),
            "human_required_fields": list(self.human_required_fields),
            "dependencies": list(self.dependencies),
            "feeds_into": list(self.feeds_into),
            "workflow_priority": self.workflow_priority,
            "metadata_status": self.metadata_status,
        }


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _coerce_record(raw: Dict[str, Any]) -> TemplateRecord:
    template_id = str(raw.get("id", "")).strip()
    if not template_id:
        raise RegistryError("Entrada sem 'id' no registry.")

    file_rel = str(raw.get("file", "")).strip()
    if not file_rel:
        raise RegistryError(f"Template {template_id} sem 'file' definido.")

    return TemplateRecord(
        id=template_id,
        name=str(raw.get("name", template_id)).strip(),
        file=file_rel,
        category=str(raw.get("category", "")).strip(),
        doc_type=str(raw.get("doc_type", "")).strip().upper(),
        description=str(raw.get("description", "")).strip(),
        keywords=_as_list(raw.get("keywords")),
        regulations=_as_list(raw.get("regulations")),
        themes=_as_list(raw.get("themes")),
        mandatory_sections=_as_list(raw.get("mandatory_sections")),
        optional_sections=_as_list(raw.get("optional_sections")),
        auto_fillable_fields=_as_list(raw.get("auto_fillable_fields")),
        human_required_fields=_as_list(raw.get("human_required_fields")),
        dependencies=_as_list(raw.get("dependencies")),
        feeds_into=_as_list(raw.get("feeds_into")),
        workflow_priority=int(raw.get("workflow_priority", 99) or 99),
        metadata_status=str(raw.get("metadata_status", "seed")).strip().lower(),
        raw=raw,
    )


@lru_cache(maxsize=1)
def _load_registry_cached() -> Dict[str, Any]:
    if not REGISTRY_PATH.exists():
        raise RegistryError(f"registry.json não encontrado em {REGISTRY_PATH}.")
    try:
        with REGISTRY_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry.json inválido: {exc}") from exc

    if not isinstance(data, dict) or "templates" not in data:
        raise RegistryError("registry.json deve conter a chave 'templates'.")

    templates_raw = data["templates"]
    if not isinstance(templates_raw, list):
        raise RegistryError("'templates' deve ser uma lista.")

    records: Dict[str, TemplateRecord] = {}
    for entry in templates_raw:
        if not isinstance(entry, dict):
            continue
        record = _coerce_record(entry)
        if record.id in records:
            raise RegistryError(f"ID duplicado no registry: {record.id}")
        records[record.id] = record

    return {
        "meta": {k: v for k, v in data.items() if k != "templates"},
        "records": records,
    }


def reload_registry() -> None:
    """Limpa a cache do registry — usar após editar registry.json em runtime."""
    _load_registry_cached.cache_clear()


def get_registry_meta() -> Dict[str, Any]:
    return dict(_load_registry_cached()["meta"])


def all_records() -> List[TemplateRecord]:
    return list(_load_registry_cached()["records"].values())


def get_record(template_id: str) -> TemplateRecord:
    records: Dict[str, TemplateRecord] = _load_registry_cached()["records"]
    record = records.get(template_id)
    if record is None:
        raise KeyError(f"Template '{template_id}' não existe no registry.")
    return record


# ---------------------------------------------------------------------------
# Operações de listagem e filtragem
# ---------------------------------------------------------------------------
def _matches_any(values: Iterable[str], wanted: Optional[str]) -> bool:
    if not wanted:
        return True
    wanted_norm = wanted.strip().lower()
    return any(v.strip().lower() == wanted_norm for v in values)


def list_templates(
    category: Optional[str] = None,
    regulation: Optional[str] = None,
    theme: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    results = []
    for record in all_records():
        if category and record.category.lower() != category.strip().lower():
            continue
        if not _matches_any(record.regulations, regulation):
            continue
        if not _matches_any(record.themes, theme):
            continue
        if doc_type and record.doc_type != doc_type.strip().upper():
            continue
        results.append(record.to_dict())

    results.sort(key=lambda r: (r["category"], r["workflow_priority"], r["id"]))
    return results


def list_categories() -> List[Dict[str, Any]]:
    counts: Dict[str, int] = {}
    for record in all_records():
        counts[record.category] = counts.get(record.category, 0) + 1
    return [{"category": k, "count": v} for k, v in sorted(counts.items())]


def list_tags() -> Dict[str, Any]:
    meta = get_registry_meta()
    taxonomy = meta.get("tag_taxonomy", {})

    regs_in_use: Dict[str, int] = {}
    themes_in_use: Dict[str, int] = {}
    for record in all_records():
        for r in record.regulations:
            regs_in_use[r] = regs_in_use.get(r, 0) + 1
        for t in record.themes:
            themes_in_use[t] = themes_in_use.get(t, 0) + 1

    return {
        "taxonomy": taxonomy,
        "regulations_in_use": [
            {"tag": k, "count": v}
            for k, v in sorted(regs_in_use.items(), key=lambda kv: -kv[1])
        ],
        "themes_in_use": [
            {"tag": k, "count": v}
            for k, v in sorted(themes_in_use.items(), key=lambda kv: -kv[1])
        ],
    }


def get_template_file_path(template_id: str) -> Path:
    record = get_record(template_id)
    path = (TEMPLATES_DIR / record.file).resolve()
    try:
        path.relative_to(TEMPLATES_DIR)
    except ValueError as exc:
        raise RegistryError(
            f"Caminho de template fora de Backend/templates: {record.file}"
        ) from exc
    if not path.exists():
        raise FileNotFoundError(
            f"Ficheiro do template '{template_id}' não encontrado em {path}."
        )
    return path


# ---------------------------------------------------------------------------
# Indexação semântica em ChromaDB
# ---------------------------------------------------------------------------
_index_lock = threading.Lock()


def _get_templates_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(name=TEMPLATES_COLLECTION_NAME)


def build_search_text(record: TemplateRecord) -> str:
    """Texto canónico embebido por template — combina nome, categoria,
    descrição, keywords, temas e regulamentos para retrieval contextual."""
    parts = [
        f"{record.id} — {record.name}",
        f"Categoria: {record.category}",
        f"Tipo: {record.doc_type}",
        record.description,
    ]
    if record.keywords:
        parts.append("Keywords: " + ", ".join(record.keywords))
    if record.themes:
        parts.append("Temas: " + ", ".join(record.themes))
    if record.regulations:
        parts.append("Regulamentos: " + ", ".join(record.regulations))
    if record.mandatory_sections:
        parts.append("Secções obrigatórias: " + ", ".join(record.mandatory_sections))
    return "\n".join(p for p in parts if p)


def _metadata_for_chroma(record: TemplateRecord) -> Dict[str, Any]:
    return {
        "template_id": record.id,
        "name": record.name,
        "category": record.category,
        "doc_type": record.doc_type,
        "regulations": ", ".join(record.regulations),
        "themes": ", ".join(record.themes),
        "workflow_priority": record.workflow_priority,
        "metadata_status": record.metadata_status,
    }


def is_indexed() -> bool:
    try:
        return _get_templates_collection().count() > 0
    except Exception:
        return False


def index_templates(rebuild: bool = False) -> Dict[str, Any]:
    """Embebe todos os templates do registry na collection ChromaDB.

    Se `rebuild` for True, apaga a collection antes. Caso contrário usa
    `upsert` para ficar idempotente.
    """
    with _index_lock:
        client = get_chroma_client()
        if rebuild:
            try:
                client.delete_collection(TEMPLATES_COLLECTION_NAME)
            except Exception:
                pass
        collection = client.get_or_create_collection(name=TEMPLATES_COLLECTION_NAME)

        records = all_records()
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        embeddings: List[List[float]] = []

        for record in records:
            text = build_search_text(record)
            ids.append(record.id)
            documents.append(text)
            metadatas.append(_metadata_for_chroma(record))
            embeddings.append(embed_query_text(text))

        if ids:
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )

        return {
            "collection": TEMPLATES_COLLECTION_NAME,
            "rebuilt": rebuild,
            "indexed_count": len(ids),
        }


def search_templates(
    query: str,
    n_results: int = 5,
    category: Optional[str] = None,
    regulation: Optional[str] = None,
    theme: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Pesquisa semântica de templates relevantes para uma frase livre.

    Filtros opcionais aplicados pós-retrieval (Chroma `where` é limitado para
    listas serializadas como string; mantemos a filtragem em Python por
    simplicidade e flexibilidade).
    """
    text = (query or "").strip()
    if not text:
        return []

    if not is_indexed():
        index_templates(rebuild=False)

    query_embedding = embed_query_text(text)
    collection = _get_templates_collection()
    raw = collection.query(
        query_embeddings=[query_embedding],
        n_results=max(n_results * 3, n_results),
        include=["documents", "metadatas", "distances"],
    )

    hits: List[Dict[str, Any]] = []
    ids = (raw.get("ids") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    for template_id, meta, distance in zip(ids, metadatas, distances):
        try:
            record = get_record(template_id)
        except KeyError:
            continue

        if category and record.category.lower() != category.strip().lower():
            continue
        if not _matches_any(record.regulations, regulation):
            continue
        if not _matches_any(record.themes, theme):
            continue

        hits.append(
            {
                "template": record.to_dict(),
                "score": max(0.0, min(1.0, float(1.0 - distance))) if distance is not None else None,
                "distance": float(distance) if distance is not None else None,
                "rationale_meta": meta,
            }
        )
        if len(hits) >= n_results:
            break

    return hits
