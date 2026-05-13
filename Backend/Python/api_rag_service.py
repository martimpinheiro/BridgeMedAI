"""
Camada de serviço RAG do BridgeMedAI.

Este módulo implementa a lógica de negócio usada pelos endpoints da API para:

- pesquisar fontes normativas relevantes a partir de embeddings locais;
- selecionar as melhores fontes para geração de resposta;
- construir prompts adequados ao tipo de pergunta detetado;
- chamar o modelo local via Ollama para produzir a resposta final;
- devolver estruturas preparadas para consumo pela API FastAPI.

Responsabilidades principais deste módulo:
- manter a lógica de orquestração fora da camada HTTP;
- traduzir o resultado do retrieval numa resposta útil e auditável;
- garantir que a resposta final inclui metadados e fontes usadas;
- reduzir respostas excessivamente especulativas através de um mecanismo
  simples de "low confidence fallback".

Este ficheiro é chamado diretamente por `api_main.py`, sendo por isso um dos
componentes centrais do backend.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

import ollama
from dotenv import load_dotenv

from rag_router_utils import (
    analyze_question,
    build_context,
    build_query_variants,
    validate_embeddings_payload,
    retrieve_relevant_indices,
    adjust_score,
    select_relevant_indices,
)
from rag_chromadb_service import query_chroma, chroma_has_documents


# ---------------------------------------------------------------------------
# Resolução de caminhos e carregamento de configuração
# ---------------------------------------------------------------------------
# O projeto usa um ficheiro `.env` localizado na pasta Backend para centralizar
# variáveis como:
# - modelo de embeddings;
# - modelo de chat;
# - caminho para o ficheiro local de embeddings.
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

VECTOR_STORE = os.getenv("VECTOR_STORE", "pickle").strip().lower()
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL")
EMBEDDINGS_PATH = (
    PROJECT_ROOT / os.getenv("EMBEDDINGS_PATH", "Backend/local_embeddings.pkl")
).resolve()


# ---------------------------------------------------------------------------
# Mapeamento de nomes internos de documentos para designações legíveis
# ---------------------------------------------------------------------------
# Este dicionário é usado para apresentar ao utilizador nomes regulatórios
# completos e consistentes.
REGULATION_LABELS = {
    "MDR": "Regulamento (UE) 2017/745 (MDR)",
    "AI_ACT": "Regulamento (UE) 2024/1689 (AI Act)",
}


# ---------------------------------------------------------------------------
# Prompt base do sistema
# ---------------------------------------------------------------------------
# Este prompt contém as regras globais que devem ser sempre respeitadas pelo
# modelo durante a geração da resposta.
SYSTEM_PROMPT_BASE = """
És um assistente regulatório do projeto BridgeMedAI.

Regras obrigatórias:
- Responde apenas com base no contexto fornecido.
- Não inventes artigos, anexos, obrigações, classes de risco ou conclusões.
- Não atribuas informação a uma citação errada.
- Usa apenas as citações exatamente como aparecem no campo "Citação" das fontes.
- Não combines artigos com anexos na mesma citação.
- Se uma afirmação vier de um considerando, cita esse considerando.
- Se uma afirmação vier de um artigo, cita esse artigo.
- Se uma afirmação vier de um anexo, cita esse anexo.
- Se uma afirmação vier de uma regra ou ponto, cita essa regra ou ponto.
- Se o contexto não for suficiente para responder com confiança, diz claramente isso.
- Responde em português de Portugal.
- Nunca alteres os nomes nem os números oficiais dos regulamentos principais fornecidos no prompt.
- Nunca cries novos regulamentos, novos números de regulamento, nem placeholders como XXX ou YYY.
- Não uses conhecimento externo ao contexto.
- Nunca cites como "FONTE 1", "FONTE 2" ou semelhante.
- Usa sempre o valor do campo "Citação:" da fonte, por exemplo "MDR Artigo 10" ou "AI_ACT Artigo 6".
- Se não souberes a citação exata, não cites essa fonte.
"""


# ---------------------------------------------------------------------------
# Instruções específicas por intenção
# ---------------------------------------------------------------------------
# O sistema adapta o comportamento da geração conforme o tipo de pergunta
# detetado no retrieval.
SYSTEM_PROMPT_BY_INTENT = {
    "regulatory_scope": """
Objetivo da resposta:
- A secção 1 já é fornecida externamente.
- Nunca cries uma nova secção 1.
- Responde apenas às secções seguintes:
  2. Porque se aplicam
  3. Pontos principais a ter em conta já no início
  4. Limitações / informação adicional necessária
  5. Citações usadas
- Se o produto for software médico com IA, considera MDR e AI Act quando ambos estiverem nos documentos-alvo.
""",

    "requirement_lookup": """
Objetivo da resposta:
- Dar uma resposta curta e direta.
- Depois explicar apenas o que as fontes sustentam.
""",

"manufacturer_obligations": """
Objetivo da resposta:
- Responder especificamente sobre obrigações do fabricante segundo o MDR.
- Priorizar MDR Artigo 10 como fonte principal.
- Usar outros artigos/anexos apenas quando forem obrigações reais do fabricante.
- Não listar obrigações de organismos notificados como se fossem obrigações do fabricante.
- Não listar atribuições do MDCG, Comissão ou autoridades competentes como obrigações do fabricante.
- Não usar Anexo VII, Artigo 55, Artigo 57, Artigo 105, Artigo 106 ou Artigo 107 como fontes para obrigações do fabricante.
- Se o utilizador pedir uma lista numerada, entregar uma lista numerada clara.
- Cada obrigação listada tem de estar sustentada pela própria fonte citada nessa linha.
- Não uses uma citação global única no fim para sustentar uma lista inteira.
- Se listares obrigações, cita cada obrigação individualmente.
""",

    "conformity_procedure": """
Objetivo da resposta:
- Explicar o procedimento de forma estruturada por passos.
- Priorizar Artigo 52 e Anexos IX, X e XI do MDR quando disponíveis.
- Não transformar perguntas de documentação em classificação de risco.
""",

    "documentation": """
Objetivo da resposta:
- Organizar a resposta por tipos de documentação.
- Priorizar MDR Anexo II, Anexo III, Artigo 10, Artigo 61 e Anexo XIV quando disponíveis.
- Não uses regras de classificação como fonte principal, exceto para explicar que a documentação depende da classe.
- Se faltarem detalhes do dispositivo, lista os campos a confirmar.
""",

    "document_generation": """
Objetivo da resposta:
- Gerar diretamente um documento estruturado e utilizável.
- O documento deve ser adaptado ao dispositivo/contexto indicado pelo utilizador e pelo histórico.
- Se faltar informação, usa "A confirmar" ou "Preencher manualmente"; não inventes.
- Para PMCF/PMS/documentação técnica, usa uma estrutura profissional.
- Não transformes a resposta numa explicação genérica de avaliação da conformidade.
- Não uses regras de classificação como corpo principal do documento; usa-as apenas para contextualizar a classe quando necessário.
""",

    "classification_risk": """
Objetivo da resposta:
- Identificar primeiro a base normativa concreta: MDR Artigo 51, MDR Anexo VIII e a Regra/Ponto aplicável.
- Se uma regra concreta do Anexo VIII estiver no contexto, aplica essa regra ao caso descrito.
- Se houver base suficiente, indica a classe provável.
- Se a classificação depender de características ainda não confirmadas, indica a classe provável e lista as condições que têm de ser confirmadas.
- Não digas apenas que falta informação se o contexto contiver uma regra aplicável clara.
- Não uses fontes sobre declaração UE de conformidade, avaliação da conformidade ou anexos que não sejam o Anexo VIII para decidir a classe.
""",
}


# ---------------------------------------------------------------------------
# Limite máximo de fontes a usar na geração, por intenção
# ---------------------------------------------------------------------------
# Nem sempre convém enviar demasiadas fontes ao modelo. Este controlo evita
# prompts desnecessariamente grandes e ajuda a manter foco.
GENERATION_MAX_ITEMS_BY_INTENT = {
    "regulatory_scope": 8,
    "requirement_lookup": 6,
    "conformity_procedure": 8,
    "documentation": 8,
    "document_generation": 8,
    "classification_risk": 6,
    "manufacturer_obligations": 8,
}


def embed_query_text(text: str) -> List[float]:
    """
    Gera embedding para uma pergunta usando o modelo configurado no Ollama.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    response = ollama.embeddings(
        model=OLLAMA_EMBED_MODEL,
        prompt=text,
    )
    return response["embedding"]


def extract_chunk_text_from_chroma_document(document: str) -> str:
    """
    Extrai apenas o conteúdo real do chunk a partir do documento serializado no Chroma.
    """
    if not document:
        return ""

    marker = "Texto:"
    if marker in document:
        return document.split(marker, 1)[1].strip()

    return document.strip()


def chroma_results_to_records(
    query_result: Dict[str, Any],
    *,
    original_question: str,
    plan: Dict[str, Any],
) -> tuple[list[dict], list[float], list[float]]:
    """
    Converte resultados do Chroma para o formato do pipeline antigo.

    Devolve:
    - records
    - base_scores
    - adjusted_scores

    Notas:
    - O Chroma devolve distância: menor é melhor.
    - Convertimos para base_score com 1 / (1 + distance).
    - Depois aplicamos adjust_score(), o mesmo reranking usado no pickle.
    - O build_context() precisa de 'chunk_text', não apenas 'text'.
    """
    metadatas = (query_result.get("metadatas") or [[]])[0]
    documents = (query_result.get("documents") or [[]])[0]
    distances = (query_result.get("distances") or [[]])[0]
    ids = (query_result.get("ids") or [[]])[0]

    records: List[Dict[str, Any]] = []
    base_scores: List[float] = []
    adjusted_scores: List[float] = []

    def clean_page(value):
        try:
            if value in (None, "", -1, "-1"):
                return None
            return int(value)
        except Exception:
            return None

    for i, meta in enumerate(metadatas):
        meta = meta or {}

        document = documents[i] if i < len(documents) else ""
        distance = float(distances[i]) if i < len(distances) else 999.0

        # menor distância = melhor score
        base_score = 1.0 / (1.0 + max(0.0, distance))

        chunk_text = extract_chunk_text_from_chroma_document(document)

        record = {
            "chunk_id": ids[i] if i < len(ids) else meta.get("chunk_id", i),
            "citation_label": str(meta.get("citation_label", "") or ""),
            "short_name": str(meta.get("short_name", "") or ""),
            "section_type": str(meta.get("section_type", "") or "").lower(),
            "section_number": str(meta.get("section_number", "") or ""),
            "section_title": str(meta.get("section_title", "") or ""),
            "page_start": clean_page(meta.get("page_start")),
            "page_end": clean_page(meta.get("page_end")),
            "chunk_text": chunk_text,
            "text": chunk_text,
        }

        adjusted_score = adjust_score(
            base_score=float(base_score),
            record=record,
            plan=plan,
            question=original_question,
        )

        records.append(record)
        base_scores.append(float(base_score))
        adjusted_scores.append(float(adjusted_score))

    return records, base_scores, adjusted_scores



def merge_chroma_candidates(
    query_results: List[Dict[str, Any]],
    *,
    original_question: str,
    plan: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], List[float], List[float], List[int]]:
    """
    Junta resultados de várias queries Chroma, deduplica e ordena por adjusted_score.

    Deduplicação:
    - usa citação + secção + início do texto
    - evita duplicados iguais vindos de várias query variants
    """
    merged_by_key: Dict[str, Dict[str, Any]] = {}

    for result in query_results:
        records, base_scores, adjusted_scores = chroma_results_to_records(
            result,
            original_question=original_question,
            plan=plan,
        )

        for record, base_score, adjusted_score in zip(records, base_scores, adjusted_scores):
            citation = (record.get("citation_label") or "").strip()
            section_number = (record.get("section_number") or "").strip()
            section_title = (record.get("section_title") or "").strip()
            text_head = (record.get("chunk_text") or "")[:180].strip()

            key = f"{citation}::{section_number}::{section_title}::{text_head}"

            prev = merged_by_key.get(key)
            if prev is None or adjusted_score > prev["adjusted_score"]:
                merged_by_key[key] = {
                    "record": record,
                    "base_score": float(base_score),
                    "adjusted_score": float(adjusted_score),
                }

    merged = list(merged_by_key.values())
    merged.sort(key=lambda x: x["adjusted_score"], reverse=True)

    records = [x["record"] for x in merged]
    base_scores = [x["base_score"] for x in merged]
    adjusted_scores = [x["adjusted_score"] for x in merged]

    # Como já vem ordenado, estes índices representam o ranking final.
    selected_indices = list(range(len(records)))

    return records, base_scores, adjusted_scores, selected_indices



def query_chroma_with_variants(
    question: str,
    plan: Dict[str, Any],
    n_results_per_query: int = 10,
) -> tuple[List[Dict[str, Any]], List[float], List[float], List[int]]:
    """
    Faz retrieval no Chroma usando query original + query variants, com filtro opcional
    por documentos-alvo.
    """
    queries = build_query_variants(question, plan)
    query_results = []

    where = None
    target_docs = plan.get("target_docs") or []
    if len(target_docs) == 1:
        where = {"short_name": target_docs[0]}
    elif len(target_docs) > 1:
        where = {"short_name": {"$in": target_docs}}

    for q in queries:
        query_embedding = embed_query_text(q)
        result = query_chroma(
            query_embedding=query_embedding,
            n_results=n_results_per_query,
            where=where,
        )
        query_results.append(result)

    return merge_chroma_candidates(
        query_results,
        original_question=question,
        plan=plan,
    )


def get_system_prompt(intent: str) -> str:
    """
    Constrói o prompt de sistema final para o modelo.

    Junta:
    - as regras base, aplicáveis a qualquer resposta;
    - as instruções específicas para a intenção detetada.

    Args:
        intent:
            Tipo de intenção inferida para a pergunta.

    Returns:
        str:
            Prompt de sistema completo.
    """
    extra = SYSTEM_PROMPT_BY_INTENT.get(
        intent,
        SYSTEM_PROMPT_BY_INTENT["requirement_lookup"],
    )
    return f"{SYSTEM_PROMPT_BASE.strip()}\n\n{extra.strip()}"


def citation_key(record: Dict[str, Any]) -> str:
    """
    Gera uma chave estável para deduplicação de fontes.

    A prioridade de identificação é:
    1. `citation_label`;
    2. `chunk_id`;
    3. fallback baseado em `id(record)`.

    Isto permite evitar selecionar várias vezes a mesma fonte lógica.

    Args:
        record:
            Registo de uma fonte recuperada.

    Returns:
        str:
            Chave textual usada para deduplicação.
    """
    citation = (record.get("citation_label") or "").strip()
    if citation:
        return f"citation::{citation}"

    chunk_id = record.get("chunk_id")
    if chunk_id is not None:
        return f"chunk::{chunk_id}"

    return f"fallback::{id(record)}"


def normalized_source_text(record: Dict[str, Any]) -> str:
    """
    Constrói uma versão textual normalizada e resumida de uma fonte.

    Esta representação é usada em várias heurísticas simples de seleção, por
    exemplo para procurar termos como 'artigo 10', 'anexo viii' ou 'regra'.

    Args:
        record:
            Registo de fonte recuperada.

    Returns:
        str:
            Texto normalizado em minúsculas.
    """
    text = " ".join([
        str(record.get("citation_label", "")),
        str(record.get("section_number", "")),
        str(record.get("section_title", "")),
        str(record.get("section_type", "")),
    ])
    return text.lower()


def try_add_best_match(
    chosen: List[int],
    used_keys: set,
    ranked: List[int],
    records: List[Dict[str, Any]],
    conditions,
) -> bool:
    """
    Tenta adicionar a melhor fonte ainda não escolhida que cumpra certas condições.

    A função percorre os índices já ordenados por relevância e seleciona o
    primeiro elemento que:
    - ainda não tenha sido usado;
    - satisfaça todas as condições fornecidas.

    Este padrão é usado para forçar a presença de fontes importantes na geração,
    por exemplo:
    - MDR Artigo 10;
    - AI Act Artigo 16;
    - MDR Anexo VIII.

    Args:
        chosen:
            Lista de índices já escolhidos para geração.
        used_keys:
            Conjunto de chaves de deduplicação já usadas.
        ranked:
            Lista de índices ordenados por prioridade.
        records:
            Lista de registos disponíveis.
        conditions:
            Conjunto/lista de funções booleanas aplicadas a cada registo.

    Returns:
        bool:
            True se foi adicionada uma fonte; False caso contrário.
    """
    for idx in ranked:
        r = records[idx]
        key = citation_key(r)
        if key in used_keys:
            continue

        if all(cond(r) for cond in conditions):
            chosen.append(idx)
            used_keys.add(key)
            return True

    return False


def specificity_rank(record: Dict[str, Any]) -> int:
    """
    Atribui um nível de especificidade à fonte.

    Quanto mais específica for a secção normativa, maior tende a ser o valor:
    - rule > point > article > annex > chapter > outros

    Esta ordenação é útil para favorecer fontes mais precisas na fase de geração.

    Args:
        record:
            Fonte normativa recuperada.

    Returns:
        int:
            Rank de especificidade.
    """
    section_type = (record.get("section_type") or "").lower()
    if section_type == "rule":
        return 5
    if section_type == "point":
        return 4
    if section_type == "article":
        return 3
    if section_type == "annex":
        return 2
    if section_type == "chapter":
        return 1
    return 0


def is_mdr_classification_source(record: Dict[str, Any]) -> bool:
    """
    Só aceita fontes realmente úteis para classificação MDR.
    Evita anexos/procedimentos que não classificam o dispositivo.
    """
    if record.get("short_name") != "MDR":
        return False

    text = normalized_source_text(record)
    section_type = (record.get("section_type") or "").lower()

    # Fontes nucleares
    if "artigo 51" in text or "classificação dos dispositivos" in text:
        return True

    if "anexo viii" in text or "regras de classificação" in text:
        return True

    # Regras/pontos concretos
    if section_type in {"rule", "point"} and "regra" in text:
        return True

    # Evitar capítulos genéricos
    if section_type == "chapter":
        return False

    return False


def classification_source_priority(record: Dict[str, Any]) -> int:
    """
    Prioridade normativa para geração em perguntas de classificação.
    """
    text = normalized_source_text(record)
    section_type = (record.get("section_type") or "").lower()

    if "regra" in text and section_type in {"rule", "point"}:
        return 100

    if "regra" in text:
        return 90

    if "anexo viii" in text:
        return 80

    if "artigo 51" in text:
        return 70

    if "classificação dos dispositivos" in text:
        return 65

    return 0


def is_bad_manufacturer_obligations_source(record: Dict[str, Any]) -> bool:
    """
    Remove fontes que não devem sustentar obrigações do fabricante.
    """
    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    if record.get("short_name") != "MDR":
        return True

    section_type = (record.get("section_type") or "").lower()

    if section_type in {"recital", "preamble", "document"}:
        return True

    bad_patterns = [
        "anexo vii",
        "organismos notificados",
        "organismo notificado",
        "requisitos a cumprir pelos organismos notificados",
        "artigo 55",
        "mecanismo de escrutínio",
        "mecanismo de escrutinio",
        "artigo 57",
        "sistema eletrónico relativo aos organismos notificados",
        "sistema eletronico relativo aos organismos notificados",
        "anexo xiii",
        "dispositivos feitos por medida",
        "procedimento aplicável aos dispositivos feitos por medida",
        "procedimento aplicavel aos dispositivos feitos por medida",
        "capítulo v",
        "capitulo v",
        "classificação e avaliação da conformidade",
        "classificacao e avaliacao da conformidade",
    ]

    return any(p in text for p in bad_patterns)


def is_good_manufacturer_obligations_source(record: Dict[str, Any]) -> bool:
    """
    Mantém fontes úteis para obrigações do fabricante no MDR.
    """
    if record.get("short_name") != "MDR":
        return False

    if is_bad_manufacturer_obligations_source(record):
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    good_patterns = [
        "artigo 10",
        "obrigações gerais dos fabricantes",
        "obrigacoes gerais dos fabricantes",
        "artigo 15",
        "pessoa responsável pela observância da regulamentação",
        "pessoa responsavel pela observancia da regulamentacao",
        "artigo 19",
        "declaração ue de conformidade",
        "declaracao ue de conformidade",
        "artigo 20",
        "marcação ce",
        "marcacao ce",
        "artigo 27",
        "udi",
        "identificação única do dispositivo",
        "identificacao unica do dispositivo",
        "artigo 29",
        "registo dos dispositivos",
        "artigo 31",
        "registo dos fabricantes",
        "artigo 61",
        "avaliação clínica",
        "avaliacao clinica",
        "artigo 83",
        "vigilância pós-comercialização",
        "vigilancia pos-comercializacao",
        "artigo 84",
        "plano de vigilância pós-comercialização",
        "plano de vigilancia pos-comercializacao",
        "artigo 86",
        "relatório periódico de segurança",
        "relatorio periodico de seguranca",
        "anexo i",
        "requisitos gerais de segurança e desempenho",
        "requisitos gerais de seguranca e desempenho",
        "anexo ii",
        "documentação técnica",
        "documentacao tecnica",
        "anexo iii",
        "documentação técnica relativa à vigilância",
        "documentacao tecnica relativa a vigilancia",
    ]

    return any(p in text for p in good_patterns)

def select_generation_indices(
    selected_indices: List[int],
    records: List[Dict[str, Any]],
    adjusted_scores,
    plan: Dict[str, Any],
) -> List[int]:
    """
    Seleciona as fontes efetivamente enviadas ao modelo para geração.

    Melhorias desta versão:
    - favorece fontes específicas em vez de capítulos genéricos;
    - para classificação MDR, força Artigo 51 + Anexo VIII + regras relevantes;
    - para termómetro / não invasivo, tenta puxar Regra 1 e fontes sobre dispositivos não invasivos;
    - evita fontes pouco úteis em classificação, como Anexo IV, Anexo VI e Declaração UE de Conformidade;
    - mantém deduplicação por citação/chunk.
    """
    if not selected_indices:
        return []

    intent = plan.get("intent", "requirement_lookup")
    target_docs = plan.get("target_docs", [])
    max_items = GENERATION_MAX_ITEMS_BY_INTENT.get(intent, 6)

    def source_text(idx: int) -> str:
        r = records[idx]
        return normalized_source_text(r) + " " + str(r.get("chunk_text", "") or "").lower()

    def is_bad_for_classification(idx: int) -> bool:
        return is_bad_classification_source(records[idx])
    
    
        

    def priority(idx: int) -> tuple:
        r = records[idx]
        text = source_text(idx)
        section_type = (r.get("section_type") or "").lower()
        short_name = r.get("short_name")

        score = float(adjusted_scores[idx])
        p = 0.0

        # Documento-alvo
        if target_docs:
            p += 0.20 if short_name in target_docs else -0.20

        # Especificidade normativa
        if section_type == "rule":
            p += 0.45
        elif section_type == "point":
            p += 0.35
        elif section_type == "article":
            p += 0.25
        elif section_type == "annex":
            p += 0.15
        elif section_type == "chapter":
            p -= 0.10

        if intent == "classification_risk":
            if "artigo 51" in text or "classificação dos dispositivos" in text or "classificacao dos dispositivos" in text:
                p += 0.50

            if "anexo viii" in text or "regras de classificação" in text or "regras de classificacao" in text:
                p += 0.55

            if "regra 1" in text:
                p += 0.75

            if "regra 2" in text or "regra 3" in text or "regra 4" in text:
                p += 0.35

            if "não invasivo" in text or "nao invasivo" in text:
                p += 0.65

            if "medição" in text or "medicao" in text or "temperatura" in text or "termómetro" in text or "termometro" in text:
                p += 0.35

            if is_bad_for_classification(idx):
                p -= 1.50

        
        elif intent == "manufacturer_obligations":
            if "artigo 10" in text or "obrigações gerais dos fabricantes" in text or "obrigacoes gerais dos fabricantes" in text:
                p += 0.90

            if "artigo 15" in text or "pessoa responsável pela observância" in text or "pessoa responsavel pela observancia" in text:
                p += 0.35

            if "artigo 19" in text or "declaração ue de conformidade" in text or "declaracao ue de conformidade" in text:
                p += 0.30

            if "artigo 20" in text or "marcação ce" in text or "marcacao ce" in text:
                p += 0.30

            if "artigo 27" in text or "udi" in text:
                p += 0.25

            if "artigo 29" in text or "registo dos dispositivos" in text:
                p += 0.25

            if "artigo 31" in text or "registo dos fabricantes" in text:
                p += 0.25

            if "artigo 61" in text or "avaliação clínica" in text or "avaliacao clinica" in text:
                p += 0.30

            if "artigo 83" in text or "vigilância pós-comercialização" in text or "vigilancia pos-comercializacao" in text:
                p += 0.30

            if "artigo 84" in text or "plano de vigilância" in text or "plano de vigilancia" in text:
                p += 0.25

            if "artigo 86" in text or "relatório periódico de segurança" in text or "relatorio periodico de seguranca" in text:
                p += 0.20

            if "anexo i" in text or "requisitos gerais de segurança e desempenho" in text or "requisitos gerais de seguranca e desempenho" in text:
                p += 0.25

            if "anexo ii" in text or "documentação técnica" in text or "documentacao tecnica" in text:
                p += 0.30

            if "anexo iii" in text or "vigilância pós-comercialização" in text or "vigilancia pos-comercializacao" in text:
                p += 0.25

            if is_bad_manufacturer_obligations_source(r):
                p -= 2.00
        
        elif intent == "regulatory_scope":
            if short_name == "MDR":
                if "artigo 5" in text or "colocação no mercado" in text or "colocacao no mercado" in text:
                    p += 0.45
                if "artigo 10" in text or "obrigações gerais dos fabricantes" in text or "obrigacoes gerais dos fabricantes" in text:
                    p += 0.50
                if "anexo i" in text or "requisitos gerais de segurança e desempenho" in text or "requisitos gerais de seguranca e desempenho" in text:
                    p += 0.35
                if "anexo ii" in text or "documentação técnica" in text or "documentacao tecnica" in text:
                    p += 0.30

            if short_name == "AI_ACT":
                if "artigo 6" in text or "alto risco" in text:
                    p += 0.45
                if "artigo 16" in text or "obrigações dos prestadores" in text or "obrigacoes dos prestadores" in text:
                    p += 0.40
                if "artigo 25" in text or "fabricantes de produtos" in text:
                    p += 0.35
                if "artigo 43" in text or "avaliação da conformidade" in text or "avaliacao da conformidade" in text:
                    p += 0.30

        elif intent in {"documentation", "document_generation"}:
            if "anexo ii" in text or "documentação técnica" in text or "documentacao tecnica" in text:
                p += 0.60

            if "anexo iii" in text or "vigilância pós-comercialização" in text or "vigilancia pos-comercializacao" in text:
                p += 0.50

            if "artigo 10" in text or "obrigações gerais dos fabricantes" in text or "obrigacoes gerais dos fabricantes" in text:
                p += 0.35

            if "artigo 61" in text or "avaliação clínica" in text or "avaliacao clinica" in text:
                p += 0.45

            if "anexo xiv" in text or "pmcf" in text or "acompanhamento clínico pós-comercialização" in text or "acompanhamento clinico pos-comercializacao" in text:
                p += 0.55

            if section_type == "rule":
                p -= 0.35

            if "regras de classificação" in text or "regras de classificacao" in text:
                p -= 0.30

        elif intent == "conformity_procedure":
            if "artigo 52" in text or "avaliação da conformidade" in text or "avaliacao da conformidade" in text:
                p += 0.55
            if "anexo ix" in text or "anexo x" in text or "anexo xi" in text:
                p += 0.45
            if "organismo notificado" in text:
                p += 0.35

        def local_specificity_rank(record: Dict[str, Any]) -> int:
            section_type = (record.get("section_type") or "").lower()

            if section_type == "rule":
                return 5
            if section_type == "point":
                return 4
            if section_type == "article":
                return 3
            if section_type == "annex":
                return 2
            if section_type == "chapter":
                return 1

            return 0

        return (p + score, local_specificity_rank(r), score)

    ranked = sorted(
        selected_indices,
        key=priority,
        reverse=True,
    )

    chosen: List[int] = []
    used_keys = set()

    def add_idx(idx: int) -> bool:
        r = records[idx]
        key = citation_key(r)

        if key in used_keys:
            return False

        if intent == "classification_risk":
            if is_bad_for_classification(idx):
                return False
            if not is_good_classification_source(r):
                return False

        if intent == "manufacturer_obligations":
            if is_bad_manufacturer_obligations_source(r):
                return False
            if not is_good_manufacturer_obligations_source(r):
                return False
        
        
        if intent == "regulatory_scope":
            if is_bad_regulatory_scope_source(r):
                return False
            if not is_good_regulatory_scope_source(r):
                return False

        chosen.append(idx)
        used_keys.add(key)
        return True

    def add_best_match(conditions) -> bool:
        for idx in ranked:
            r = records[idx]
            text = source_text(idx)
            if all(cond(r, text) for cond in conditions):
                return add_idx(idx)
        return False

    
    
    # -----------------------------------------------------------------------
    # Obrigações do fabricante MDR — fontes nucleares
    # -----------------------------------------------------------------------
    if intent == "manufacturer_obligations":
        for wanted in [
            "artigo 10",
            "artigo 15",
            "artigo 19",
            "artigo 20",
            "artigo 27",
            "artigo 29",
            "artigo 31",
            "artigo 61",
            "artigo 83",
            "artigo 84",
            "artigo 86",
            "anexo i",
            "anexo ii",
            "anexo iii",
        ]:
            add_best_match([
                lambda r, text, wanted=wanted: r.get("short_name") == "MDR",
                lambda r, text, wanted=wanted: wanted in text,
            ])
    
    
    # -----------------------------------------------------------------------
    # Classificação MDR — fontes nucleares
    # -----------------------------------------------------------------------
    elif intent == "classification_risk":
        # Base legal geral da classificação
        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "artigo 51" in text or "classificação dos dispositivos" in text or "classificacao dos dispositivos" in text,
        ])

        # Anexo VIII — regras de classificação
        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "anexo viii" in text and ("regras de classificação" in text or "regras de classificacao" in text),
        ])

        # Regra 1 / dispositivos não invasivos
        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "regra 1" in text or "não invasivo" in text or "nao invasivo" in text,
        ])

        # Caso haja uma regra sobre medição/temperatura, também é útil
        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "medição" in text or "medicao" in text or "temperatura" in text or "termómetro" in text or "termometro" in text,
        ])

    # -----------------------------------------------------------------------
    # Âmbito regulatório — fontes nucleares
    # -----------------------------------------------------------------------
    elif intent == "regulatory_scope":
        if "MDR" in target_docs:
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: "artigo 5" in text or "colocação no mercado" in text or "colocacao no mercado" in text,
            ])
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: "artigo 10" in text or "obrigações gerais dos fabricantes" in text or "obrigacoes gerais dos fabricantes" in text,
            ])
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: "anexo i" in text or "requisitos gerais de segurança e desempenho" in text or "requisitos gerais de seguranca e desempenho" in text,
            ])
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: "anexo ii" in text or "documentação técnica" in text or "documentacao tecnica" in text,
            ])

        if "AI_ACT" in target_docs:
            add_best_match([
                lambda r, text: r.get("short_name") == "AI_ACT",
                lambda r, text: "artigo 6" in text or "alto risco" in text,
            ])
            add_best_match([
                lambda r, text: r.get("short_name") == "AI_ACT",
                lambda r, text: "artigo 16" in text or "obrigações dos prestadores" in text or "obrigacoes dos prestadores" in text,
            ])
            add_best_match([
                lambda r, text: r.get("short_name") == "AI_ACT",
                lambda r, text: "artigo 25" in text or "fabricantes de produtos" in text,
            ])
            
            
    # -----------------------------------------------------------------------
    # Documentação / geração documental — fontes nucleares
    # -----------------------------------------------------------------------
    elif intent in {"documentation", "document_generation"}:
        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "anexo ii" in text or "documentação técnica" in text or "documentacao tecnica" in text,
        ])

        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "anexo iii" in text or "vigilância pós-comercialização" in text or "vigilancia pos-comercializacao" in text,
        ])

        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "artigo 10" in text or "obrigações gerais dos fabricantes" in text or "obrigacoes gerais dos fabricantes" in text,
        ])

        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "artigo 61" in text or "avaliação clínica" in text or "avaliacao clinica" in text,
        ])

        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "anexo xiv" in text or "pmcf" in text or "acompanhamento clínico pós-comercialização" in text or "acompanhamento clinico pos-comercializacao" in text,
        ])

    # Completar com os melhores restantes
    for idx in ranked:
        if len(chosen) >= max_items:
            break
        add_idx(idx)

    return chosen[:max_items]

def build_regulations_block(target_docs: List[str]) -> str:
    """
    Constrói uma lista textual dos regulamentos principais aplicáveis.

    Args:
        target_docs:
            Lista de identificadores internos de documentos-alvo.

    Returns:
        str:
            Bloco textual com os nomes completos dos regulamentos.
    """
    regulation_lines = []

    for doc in target_docs:
        if doc in REGULATION_LABELS:
            regulation_lines.append(f"- {REGULATION_LABELS[doc]}")

    if not regulation_lines:
        return "- Sem enquadramento principal pré-identificado"

    return "\n".join(regulation_lines)


def build_fixed_regulations_section(plan: Dict[str, Any]) -> str:
    """
    Constrói a secção fixa '1. Regulamentos principais aplicáveis'.

    Esta secção é gerada fora do LLM para evitar que o modelo:
    - altere nomes oficiais;
    - invente números de regulamento;
    - apresente artigos como se fossem regulamentos principais.

    Args:
        plan:
            Plano inferido na fase de retrieval.

    Returns:
        str:
            Secção textual pronta a inserir antes da resposta gerada.
    """
    target_docs = plan.get("target_docs", [])

    lines = ["1. Regulamentos principais aplicáveis"]

    if not target_docs:
        lines.append("- Não foi possível identificar automaticamente um regulamento principal.")
        return "\n".join(lines)

    for doc in target_docs:
        if doc in REGULATION_LABELS:
            lines.append(f"- {REGULATION_LABELS[doc]}")

    return "\n".join(lines)


def build_history_block(history: Optional[List[Dict[str, str]]], max_items: int = 8) -> str:
    """
    Constrói um bloco textual com o histórico recente da conversa.
    """
    if not history:
        return ""

    lines = []
    for msg in history[-max_items:]:
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()

        if not role or not content:
            continue

        if role == "user":
            lines.append(f"Utilizador: {content}")
        elif role == "assistant":
            lines.append(f"Assistente: {content}")

    return "\n".join(lines).strip()


def build_contextual_question(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Enriquece a pergunta atual com histórico recente quando existir.
    """
    history_block = build_history_block(history, max_items=6)

    if not history_block:
        return question

    return (
        f"Histórico recente da conversa:\n{history_block}\n\n"
        f"Pergunta atual do utilizador:\n{question}"
    )

def build_user_prompt(
    user_question: str,
    context: str,
    intent: str,
    plan: Dict[str, Any],
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Constrói o prompt de utilizador enviado ao modelo de chat.

    Este prompt inclui:
    - intenção detetada;
    - documentos-alvo;
    - regulamentos principais já fixados;
    - pergunta original;
    - contexto textual construído a partir das fontes selecionadas;
    - instruções adicionais por tipo de pergunta;
    - regras finais de resposta.

    Args:
        user_question:
            Pergunta original do utilizador.
        context:
            Contexto normativo preparado para o modelo.
        intent:
            Intenção detetada.
        plan:
            Plano inferido no retrieval.

    Returns:
        str:
            Prompt completo para o modelo de chat.
    """
    target_docs = plan.get("target_docs", [])
    target_docs_text = ", ".join(target_docs) if target_docs else "sem documento-alvo fixo"
    regulations_block = build_regulations_block(target_docs)
    history_block = build_history_block(history)

    intent_specific_instruction = {
        "regulatory_scope": """
Instruções adicionais:
- A secção 1 já está determinada externamente e não deves reescrevê-la.
- Não cries uma nova secção 1.
- Começa diretamente na secção 2.
- Não respondas com artigos como se fossem regulamentos principais.
""",
        "requirement_lookup": """
Instruções adicionais:
- Dá primeiro uma resposta curta e direta.
- Depois explica apenas o que o contexto sustenta.
""",
        "conformity_procedure": """
Instruções adicionais:
- Organiza a resposta por passos.
""",
                "documentation": """
Instruções adicionais:
- Organiza a resposta por tipos de documentação.
- Prioriza documentação técnica, avaliação clínica, PMS, PMCF, gestão de risco, requisitos gerais de segurança e desempenho e obrigações do fabricante.
- Não centres a resposta em regras de classificação, exceto para dizer que a documentação depende da classe do dispositivo.
- Indica claramente o que é obrigatório e o que depende da classe/finalidade do dispositivo.
""",
"classification_risk": """
Instruções adicionais:
- Identifica primeiro a base normativa concreta: MDR Artigo 51, MDR Anexo VIII e a regra aplicável.
- Para dispositivos não invasivos simples, usa a Regra 1 do Anexo VIII.
- Se o contexto disser que todos os dispositivos não invasivos são Classe I salvo aplicação de outras regras, conclui claramente: "Classe provável: Classe I".
- Se a pergunta disser apenas que é um termómetro não invasivo, responde que a classe provável é Classe I pela Regra 1, salvo se tiver funcionalidades que ativem outra regra.
- Se a pergunta mencionar termómetro digital ativo, diagnóstico direto, monitorização ou parâmetros fisiológicos vitais, considera também a Regra 10 e explica que a classe pode mudar conforme a finalidade concreta.
- Não uses fontes sobre documentação técnica, declaração UE de conformidade, registo, EUDAMED, avaliação da conformidade, organismos notificados ou considerandos para decidir a classe.
- Termina com uma conclusão prática curta: "Classe provável: ...", seguida das condições a confirmar.
""",

"manufacturer_obligations": """
Instruções adicionais:
- Responde apenas sobre obrigações do fabricante segundo o MDR.
- Usa o MDR Artigo 10 como fonte principal.
- Se o utilizador pedir 10 obrigações, enumera 10 obrigações reais e não 10 fontes.
- Cada obrigação numerada deve terminar com a citação correta.
- Não uses uma única citação final para sustentar a lista inteira.
- Não incluas obrigações de organismos notificados, autoridades competentes, MDCG, Comissão ou mandatários como se fossem obrigações do fabricante.
- Não uses fontes sobre MDCG, Comissão, autoridades competentes, organismos notificados ou anexos institucionais.
- Podes mencionar a pessoa responsável pela observância da regulamentação, declaração UE de conformidade, marcação CE, UDI, registo, avaliação clínica, PMS/PMCF e documentação técnica quando o contexto o sustentar.
- No fim, inclui apenas as citações realmente usadas.
""",

"document_generation": """
Instruções adicionais:
- Gera diretamente o documento pedido.
- Se o utilizador pedir PMCF ou PCMF, cria um Plano PMCF estruturado.
- Usa o histórico recente para identificar o dispositivo referido, por exemplo "primeira questão".
- Se só souberes que é um termómetro não invasivo, assume apenas isso e marca o resto como "A confirmar".
- Não mudes para procedimento de avaliação da conformidade, salvo se o utilizador pedir isso expressamente.
- Não uses regras de classificação como corpo principal do documento; usa-as apenas para contextualizar a classe do dispositivo.
- Estrutura recomendada para PMCF:
  1. Identificação do dispositivo
  2. Enquadramento regulamentar
  3. Objetivos do PMCF
  4. População/utilizadores previstos
  5. Dados clínicos a recolher
  6. Métodos e atividades PMCF
  7. Indicadores, critérios de aceitação e sinais de alerta
  8. Periodicidade e responsabilidades
  9. Integração com avaliação clínica, PMS e gestão de risco
  10. Limitações e informação em falta
  11. Citações usadas
""",
    }.get(intent, "")

    return f"""
Tipo de pergunta detetado:
{intent}

Documentos-alvo:
{target_docs_text}

Regulamentos principais já identificados externamente:
{regulations_block}

Histórico recente da conversa:
{history_block if history_block else "Sem histórico relevante."}

Pergunta atual do utilizador:
{user_question}

Contexto recuperado:
{context}

{intent_specific_instruction}

Regras finais:
- Responde apenas com base no contexto.
- Quando fizeres uma afirmação normativa, associa-a à citação correta usando exatamente o campo "Citação:".
- Nunca escrevas "FONTE 1", "FONTE 2", "FONTE 3" ou semelhante na resposta final.
- Não cries uma nova secção 1.
- No fim, inclui apenas as citações realmente usadas.
"""


def sanitize_generated_answer(text: str) -> str:
    """
    Limpa a resposta gerada pelo modelo antes de a devolver.

    Objetivos desta sanitização:
    - remover repetições indevidas da secção 1;
    - eliminar placeholders incorretos como XXX/YYY;
    - cortar cabeçalhos iniciais redundantes;
    - reduzir quebras de linha excessivas.

    Args:
        text:
            Texto bruto devolvido pelo modelo.

    Returns:
        str:
            Texto limpo e pronto a ser devolvido ao utilizador.
    """
    if not text:
        return ""

    cleaned = text.strip()

    # Tenta posicionar o texto no início da secção 2, caso o modelo tenha
    # incluído elementos adicionais antes do formato esperado.
    match = re.search(r"(?m)^\s*(?:##\s*)?2[\.\)]?\s*", cleaned)
    if match:
        cleaned = cleaned[match.start():].strip()

    cleaned = re.sub(r"(?mi)^.*\bXXX\b.*$", "", cleaned)
    cleaned = re.sub(r"(?mi)^.*\bYYY\b.*$", "", cleaned)
    cleaned = re.sub(r"(?mi)^\s*1[\.\)]\s*regulamentos principais aplic[aá]veis.*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned


def has_minimum_retrieval_confidence(
    selected_indices: List[int],
    adjusted_scores,
) -> bool:
    """
    Verifica se a confiança mínima do retrieval é suficiente para gerar resposta.

    Atualmente usa uma heurística simples:
    - se o melhor score ajustado for inferior a 0.36, considera-se que o
      contexto recuperado é fraco para sustentar uma resposta conclusiva.

    Args:
        selected_indices:
            Índices das fontes recuperadas.
        adjusted_scores:
            Vetor de scores ajustados.

    Returns:
        bool:
            True se houver confiança mínima suficiente; False caso contrário.
    """
    if not selected_indices:
        return False

    best = float(adjusted_scores[selected_indices[0]])
    top_k = selected_indices[:3]
    avg_top = sum(float(adjusted_scores[i]) for i in top_k) / max(1, len(top_k))

    return best >= 0.25 or avg_top >= 0.34


def records_preview(
    indices: List[int],
    records: List[Dict[str, Any]],
    adjusted_scores,
) -> List[Dict[str, Any]]:
    """
    Constrói uma versão resumida e serializável das fontes selecionadas.

    Esta função prepara os registos para resposta da API, removendo o texto
    completo dos chunks e mantendo apenas os metadados principais.

    Args:
        indices:
            Índices dos registos a resumir.
        records:
            Lista completa de registos disponíveis.
        adjusted_scores:
            Scores ajustados associados aos registos.

    Returns:
        List[Dict[str, Any]]:
            Lista de dicionários prontos para resposta JSON.
    """
    out = []
    for idx in indices:
        r = records[idx]
        out.append({
            "citation_label": r.get("citation_label", ""),
            "short_name": r.get("short_name", ""),
            "section_type": r.get("section_type", ""),
            "section_number": r.get("section_number", ""),
            "section_title": r.get("section_title", ""),
            "page_start": r.get("page_start", ""),
            "page_end": r.get("page_end", ""),
            "score_adjusted": max(0.0, min(1.0, float(adjusted_scores[idx]))),
        })
    return out


def build_low_confidence_answer(
    plan: Dict[str, Any],
    generation_indices: List[int],
    records: List[Dict[str, Any]],
    adjusted_scores,
) -> str:
    """
    Constrói uma resposta conservadora quando o retrieval é fraco.

    Em vez de forçar uma resposta potencialmente incorreta, o sistema devolve:
    - a secção fixa dos regulamentos principais aplicáveis;
    - uma explicação de que a confiança é insuficiente;
    - pontos adicionais a confirmar;
    - algumas citações recuperadas, quando existirem.

    Args:
        plan:
            Plano inferido no retrieval.
        generation_indices:
            Fontes selecionadas para geração.
        records:
            Lista completa de registos.
        adjusted_scores:
            Scores ajustados das fontes.

    Returns:
        str:
            Resposta textual segura para cenários de baixa confiança.
    """
    fixed_regulations_section = build_fixed_regulations_section(plan)
    citations = [
        records[idx].get("citation_label", "")
        for idx in generation_indices[:4]
        if records[idx].get("citation_label", "")
    ]

    body = [
        "2. Porque se aplicam / o que o contexto permite dizer",
        "- O contexto recuperado não é suficientemente forte para sustentar uma resposta conclusiva.",
        "- Há indícios de enquadramento regulatório relevante, mas não há base suficiente para fechar a conclusão com confiança.",
        "",
        "3. Pontos principais a ter em conta já no início",
        "- Confirmar a finalidade prevista do produto.",
        "- Confirmar o modo de utilização, invasividade, duração de contacto e contexto clínico.",
        "",
        "4. Limitações / informação adicional necessária",
        "- Falta contexto normativo suficientemente forte e específico para responder com segurança.",
    ]

    if citations:
        body.extend(["", "5. Citações usadas"])
        body.extend([f"- {c}" for c in citations])

    return f"{fixed_regulations_section}\n\n" + "\n".join(body).strip()


def is_bad_regulatory_scope_source(record: Dict[str, Any]) -> bool:
    """
    Remove fontes pouco úteis para respostas de enquadramento regulatório geral.
    """
    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    section_type = (record.get("section_type") or "").lower()

    if section_type in {"recital", "preamble", "document"}:
        return True

    bad_patterns = [
        # organismos notificados / avaliação da conformidade / escrutínio
        "anexo vii",
        "organismos notificados",
        "organismo notificado",
        "requisitos a cumprir pelos organismos notificados",
        "artigo 55",
        "mecanismo de escrutínio",
        "mecanismo de escrutinio",
        "artigo 57",
        "sistema eletrónico relativo aos organismos notificados",
        "sistema eletronico relativo aos organismos notificados",
        "capítulo v",
        "capitulo v",
        "classificação e avaliação da conformidade",
        "classificacao e avaliacao da conformidade",

        # dispositivos feitos por medida / anexos que não são obrigações gerais do fabricante
        "anexo xiii",
        "dispositivos feitos por medida",
        "procedimento aplicável aos dispositivos feitos por medida",
        "procedimento aplicavel aos dispositivos feitos por medida",

        # MDCG / Comissão / autoridades — NÃO são obrigações do fabricante
        "artigo 105",
        "atribuições do mdcg",
        "atribuicoes do mdcg",
        "mdcg",
        "artigo 106",
        "artigo 107",
        "comissão",
        "comissao",
        "autoridades competentes",
        "autoridade competente",
        "grupo de coordenação dos dispositivos médicos",
        "grupo de coordenacao dos dispositivos medicos",
    ]

    return any(p in text for p in bad_patterns)


def is_good_regulatory_scope_source(record: Dict[str, Any]) -> bool:
    """
    Fontes úteis para dizer que regulamentos/artigos/anexos principais se aplicam.
    """
    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    short_name = record.get("short_name")

    if short_name == "MDR":
        good_mdr = [
            "artigo 5",
            "artigo 10",
            "artigo 51",
            "artigo 52",
            "artigo 61",
            "anexo i",
            "anexo ii",
            "anexo iii",
            "anexo viii",
            "anexo xiv",
            "requisitos gerais de segurança e desempenho",
            "requisitos gerais de seguranca e desempenho",
            "documentação técnica",
            "documentacao tecnica",
            "avaliação clínica",
            "avaliacao clinica",
            "vigilância pós-comercialização",
            "vigilancia pos-comercializacao",
            "regras de classificação",
            "regras de classificacao",
        ]
        return any(p in text for p in good_mdr)

    if short_name == "AI_ACT":
        good_ai = [
            "artigo 6",
            "artigo 9",
            "artigo 10",
            "artigo 11",
            "artigo 16",
            "artigo 25",
            "artigo 43",
            "alto risco",
            "sistema de ia de risco elevado",
            "documentação técnica",
            "documentacao tecnica",
            "avaliação da conformidade",
            "avaliacao da conformidade",
        ]
        return any(p in text for p in good_ai)

    return False


def is_bad_classification_source(record: Dict[str, Any]) -> bool:
    """
    Remove fontes que não servem para decidir classe de risco MDR.

    Importante:
    - Não usar simples 'anexo vi' in text, porque isso apanha 'anexo viii'.
    - Não usar simples 'artigo 1' in text, porque pode criar falsos positivos.
    """
    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    section_type = (record.get("section_type") or "").lower()

    if section_type in {"recital", "preamble", "document"}:
        return True

    # Nunca bloquear fontes nucleares de classificação
    if re.search(r"\bartigo\s+51\b", text):
        return False

    if re.search(r"\banexo\s+viii\b", text):
        return False

    if re.search(r"\bregra\s+\d+\b", text):
        return False

    bad_regex_patterns = [
        r"\banexo\s+ii\b",
        r"\banexo\s+iii\b",
        r"\banexo\s+iv\b",
        r"\banexo\s+vi\b",
        r"\banexo\s+vii\b",
        r"\banexo\s+ix\b",
        r"\banexo\s+x\b",
        r"\banexo\s+xi\b",
        r"\bartigo\s+1\b",
        r"\bartigo\s+10\b",
        r"\bartigo\s+52\b",
        r"\bartigo\s+84\b",
    ]

    if any(re.search(pattern, text) for pattern in bad_regex_patterns):
        return True

    bad_text_patterns = [
        "documentação técnica",
        "documentacao tecnica",
        "vigilância pós-comercialização",
        "vigilancia pos-comercializacao",
        "declaração ue de conformidade",
        "declaracao ue de conformidade",
        "informações a apresentar aquando do registo",
        "informacoes a apresentar aquando do registo",
        "registo de dispositivos",
        "operadores",
        "organismos notificados",
        "avaliação da conformidade",
        "avaliacao da conformidade",
        "organismo notificado",
        "eudamed",
        "certificado de venda livre",
        "objeto e âmbito de aplicação",
        "objecto e ambito de aplicacao",
        "obrigações gerais dos fabricantes",
        "obrigacoes gerais dos fabricantes",
        "procedimentos de avaliação da conformidade",
        "procedimentos de avaliacao da conformidade",
        "plano de monitorização pós-comercialização",
        "plano de monitorizacao pos-comercializacao",
    ]

    return any(pattern in text for pattern in bad_text_patterns)


def is_good_classification_source(record: Dict[str, Any]) -> bool:
    """
    Mantém apenas fontes realmente úteis para classificação MDR.
    """
    if record.get("short_name") != "MDR":
        return False

    if is_bad_classification_source(record):
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    if re.search(r"\bartigo\s+51\b", text):
        return True

    if re.search(r"\banexo\s+viii\b", text):
        return True

    if re.search(r"\bregra\s+\d+\b", text):
        return True

    good_text_patterns = [
        "classificação dos dispositivos",
        "classificacao dos dispositivos",
        "regras de classificação",
        "regras de classificacao",
        "dispositivos não invasivos",
        "dispositivos nao invasivos",
        "classe i",
        "classe iia",
        "classe iib",
        "classe iii",
    ]

    return any(pattern in text for pattern in good_text_patterns)



def select_chroma_retrieved_indices(
    records: List[Dict[str, Any]],
    adjusted_scores: List[float],
    plan: Dict[str, Any],
    max_items: int = 18,
) -> List[int]:
    """
    Seleção própria para resultados vindos do Chroma.

    - classification_risk: mantém só fontes boas de classificação.
    - documentation/document_generation: força Anexo II, Anexo III, Artigo 10, Artigo 61, Anexo XIV/PMCF.
    - outros intents: ranking normal.
    """
    if not records:
        return []

    intent = plan.get("intent", "requirement_lookup")

    ranked = sorted(
        range(len(records)),
        key=lambda i: float(adjusted_scores[i]),
        reverse=True,
    )

    selected: List[int] = []
    seen = set()

    def key_for(idx: int) -> str:
        r = records[idx]
        citation = (r.get("citation_label") or "").strip()
        section_number = (r.get("section_number") or "").strip()
        chunk_id = str(r.get("chunk_id") or "").strip()

        if citation and section_number:
            return f"{citation}::{section_number}"

        if citation and chunk_id:
            return f"{citation}::{chunk_id}"

        if citation:
            return f"citation::{citation}"

        if chunk_id:
            return f"chunk::{chunk_id}"

        return f"idx::{idx}"

    def source_text(idx: int) -> str:
        r = records[idx]
        return " ".join([
            str(r.get("citation_label", "")),
            str(r.get("section_number", "")),
            str(r.get("section_title", "")),
            str(r.get("section_type", "")),
            str(r.get("chunk_text", ""))[:1800],
        ]).lower()

    def add(idx: int) -> None:
        k = key_for(idx)
        if k in seen:
            return
        selected.append(idx)
        seen.add(k)
        
        
    if intent == "manufacturer_obligations":
        obligations_ranked = [
            idx for idx in ranked
            if is_good_manufacturer_obligations_source(records[idx])
            and not is_bad_manufacturer_obligations_source(records[idx])
        ]

        for wanted in [
            "artigo 10",
            "artigo 15",
            "artigo 19",
            "artigo 20",
            "artigo 27",
            "artigo 29",
            "artigo 31",
            "artigo 61",
            "artigo 83",
            "artigo 84",
            "artigo 86",
            "anexo i",
            "anexo ii",
            "anexo iii",
        ]:
            for idx in obligations_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in obligations_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]

    if intent == "classification_risk":
        classification_ranked = [
            idx for idx in ranked
            if is_good_classification_source(records[idx])
        ]

        for idx in classification_ranked:
            t = source_text(idx)
            if "artigo 51" in t or "classificação dos dispositivos" in t or "classificacao dos dispositivos" in t:
                add(idx)
                break

        for idx in classification_ranked:
            t = source_text(idx)
            if "anexo viii" in t and ("regras de classificação" in t or "regras de classificacao" in t):
                add(idx)
                break

        for idx in classification_ranked:
            t = source_text(idx)
            if "regra 1" in t or "não invasivo" in t or "nao invasivo" in t:
                add(idx)

        for idx in classification_ranked:
            t = source_text(idx)
            if (
                "regra 10" in t
                or "regra 11" in t
                or "medição" in t
                or "medicao" in t
                or "temperatura" in t
                or "termómetro" in t
                or "termometro" in t
                or "monitorização" in t
                or "monitorizacao" in t
                or "diagnóstico" in t
                or "diagnostico" in t
                or "software" in t
            ):
                add(idx)

        for idx in classification_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]

    if intent in {"documentation", "document_generation"}:
        for idx in ranked:
            t = source_text(idx)
            if "anexo ii" in t or "documentação técnica" in t or "documentacao tecnica" in t:
                add(idx)
                break

        for idx in ranked:
            t = source_text(idx)
            if (
                "anexo iii" in t
                or "vigilância pós-comercialização" in t
                or "vigilancia pos-comercializacao" in t
                or "pms" in t
            ):
                add(idx)
                break

        for idx in ranked:
            t = source_text(idx)
            if "artigo 10" in t or "obrigações gerais dos fabricantes" in t or "obrigacoes gerais dos fabricantes" in t:
                add(idx)
                break

        for idx in ranked:
            t = source_text(idx)
            if (
                "artigo 61" in t
                or "avaliação clínica" in t
                or "avaliacao clinica" in t
                or "anexo xiv" in t
                or "pmcf" in t
                or "acompanhamento clínico pós-comercialização" in t
                or "acompanhamento clinico pos-comercializacao" in t
            ):
                add(idx)

        for idx in ranked:
            if len(selected) >= max_items:
                break

            t = source_text(idx)
            section_type = (records[idx].get("section_type") or "").lower()

            if section_type == "rule":
                continue

            if any(bad in t for bad in [
                "regras de classificação",
                "regras de classificacao",
                "regra 1",
                "regra 7",
                "regra 10",
                "regra 11",
                "regra 12",
                "regra 17",
                "regra 22",
            ]):
                continue

            add(idx)

        return selected[:max_items]
    
    
    if intent == "regulatory_scope":
        scope_ranked = [
            idx for idx in ranked
            if is_good_regulatory_scope_source(records[idx])
            and not is_bad_regulatory_scope_source(records[idx])
        ]

        # MDR — fontes nucleares
        for wanted in [
            "artigo 5",
            "artigo 10",
            "anexo i",
            "anexo ii",
            "artigo 61",
            "anexo xiv",
            "anexo viii",
        ]:
            for idx in scope_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        # AI Act — fontes nucleares
        for wanted in [
            "artigo 6",
            "artigo 9",
            "artigo 10",
            "artigo 11",
            "artigo 16",
            "artigo 25",
            "artigo 43",
        ]:
            for idx in scope_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in scope_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]

    for idx in ranked:
        if len(selected) >= max_items:
            break
        add(idx)

    return selected[:max_items]


def search_question(question: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """
    Executa apenas a fase de pesquisa semântica.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    question_clean = (question or "").strip()
    if not question_clean:
        raise ValueError("A pergunta não pode estar vazia.")

    retrieval_question = build_contextual_question(question_clean, history) if history else question_clean
    plan = analyze_question(retrieval_question)

    if VECTOR_STORE == "chroma" and chroma_has_documents():
        records, base_scores, adjusted_scores, selected_indices = query_chroma_with_variants(
            retrieval_question,
            plan,
            n_results_per_query=10,
        )

        if plan.get("intent") in {"manufacturer_obligations", "classification_risk", "documentation", "document_generation"}:
            selected_indices = select_chroma_retrieved_indices(
                records=records,
                adjusted_scores=adjusted_scores,
                plan=plan,
                max_items=18,
            )
        else:
            selected_indices = select_relevant_indices(
                records=records,
                adjusted_scores=np.array(adjusted_scores, dtype=float),
                plan=plan,
            )

        return {
            "intent": plan["intent"],
            "target_docs": plan["target_docs"],
            "results": records_preview(selected_indices, records, adjusted_scores),
        }

    payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
    all_records = payload["records"]
    embeddings = payload["embeddings"]

    selected_indices, base_scores, adjusted_scores, plan = retrieve_relevant_indices(
        question=retrieval_question,
        records=all_records,
        embeddings=embeddings,
        embed_model=OLLAMA_EMBED_MODEL,
    )

    return {
        "intent": plan["intent"],
        "target_docs": plan["target_docs"],
        "results": records_preview(selected_indices, all_records, adjusted_scores),
    }


def answer_question(question: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    if not OLLAMA_CHAT_MODEL:
        raise ValueError("Falta OLLAMA_CHAT_MODEL no .env")

    question_clean = (question or "").strip()
    if not question_clean:
        raise ValueError("A pergunta não pode estar vazia.")

    is_follow_up = (
        len(question_clean) < 120
        or any(
            expr in question_clean.lower()
            for expr in [
                "e agora",
                "agora",
                "isso",
                "esse",
                "essa",
                "este",
                "esta",
                "o mesmo",
                "faz o documento",
                "gera o pmcf",
                "faz agora o documento pmcf",
            ]
        )
    )

    retrieval_question = (
        build_contextual_question(question_clean, history)
        if is_follow_up
        else question_clean
    )

    plan = analyze_question(retrieval_question)

    if VECTOR_STORE == "chroma" and chroma_has_documents():
        n_results = 25 if plan.get("intent") in {"manufacturer_obligations", "classification_risk", "documentation", "document_generation"} else 12

        records, base_scores, adjusted_scores, _ = query_chroma_with_variants(
            retrieval_question,
            plan,
            n_results_per_query=n_results,
        )

        if not records:
            raise ValueError("Não foi possível recuperar contexto relevante.")

        selected_indices = select_chroma_retrieved_indices(
            records=records,
            adjusted_scores=adjusted_scores,
            plan=plan,
            max_items=18,
        )
        retrieval_backend = "chroma"
        
    else:
        payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
        records = payload["records"]
        embeddings = payload["embeddings"]

        selected_indices, base_scores, adjusted_scores, plan = retrieve_relevant_indices(
            question=retrieval_question,
            records=records,
            embeddings=embeddings,
            embed_model=OLLAMA_EMBED_MODEL,
        )
        retrieval_backend = "pickle"

    if not selected_indices:
        raise ValueError("Não foi possível recuperar contexto relevante.")

    generation_indices = select_generation_indices(
        selected_indices=selected_indices,
        records=records,
        adjusted_scores=adjusted_scores,
        plan=plan,
    )

    if not generation_indices:
        raise ValueError("Não foi possível selecionar fontes para gerar a resposta.")

    if not has_minimum_retrieval_confidence(selected_indices, adjusted_scores):
        final_answer = build_low_confidence_answer(
            plan,
            generation_indices,
            records,
            adjusted_scores,
        )
        return {
            "intent": plan["intent"],
            "target_docs": plan["target_docs"],
            "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
            "generation_sources": records_preview(generation_indices, records, adjusted_scores),
            "answer": final_answer,
            "retrieval_backend": retrieval_backend,
        }

    context = build_context(generation_indices, records)
    system_prompt = get_system_prompt(plan["intent"])
    prompt = build_user_prompt(
        question,
        context,
        plan["intent"],
        plan,
        history=history,
    )

    response = ollama.chat(
        model=OLLAMA_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )

    fixed_regulations_section = build_fixed_regulations_section(plan)
    generated_text = sanitize_generated_answer(response["message"]["content"])
    final_answer = f"{fixed_regulations_section}\n\n{generated_text}".strip()

    return {
        "intent": plan["intent"],
        "target_docs": plan["target_docs"],
        "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
        "generation_sources": records_preview(generation_indices, records, adjusted_scores),
        "answer": final_answer,
        "retrieval_backend": retrieval_backend,
    }