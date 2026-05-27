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

try:
    from api_user_documents_service import query_user_documents_for_rag
except Exception:
    query_user_documents_for_rag = None


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
- Nunca reproduzas os metadados completos das fontes, como "Documento:", "Tipo:", "Secção:", "Título:" ou "Páginas:".
- Não copies o bloco de contexto recuperado para a resposta final.
- Usa as fontes apenas para fundamentar a resposta, citando só a etiqueta do campo "Citação:".
- Não respondas escrevendo "Citação: ... Documento: ... Tipo: ...".
- O contexto pode conter fontes normativas oficiais e documentos internos do utilizador.
- As fontes normativas oficiais, como MDR e AI Act, prevalecem sempre sobre documentos internos.
- Documentos internos do utilizador são contexto complementar e devem ser identificados como documentos internos.
- Se houver conflito entre documento interno e MDR/AI Act, identifica o conflito e avisa que prevalece a fonte normativa oficial.
- Quando usares informação de um documento interno, cita exatamente a etiqueta "Documento interno: ...".
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
- Sistema de vigilância/monitorização pós-comercialização deve ser citado com MDR Artigo 83, não MDR Artigo 61.
- Avaliação clínica deve ser citada com MDR Artigo 61.
- UDI / identificação única do dispositivo deve ser citado com MDR Artigo 27 quando essa fonte estiver no contexto.
- Registo dos dispositivos deve ser citado com MDR Artigo 29.
- Declaração UE de conformidade deve ser citada com MDR Artigo 19; usa MDR ANEXO IV apenas para o conteúdo da declaração.
- Não repitas a mesma obrigação com palavras diferentes.
""",

    "conformity_procedure": """
Objetivo da resposta:
- Explicar o procedimento de forma estruturada por passos.
- Priorizar MDR Artigo 52 e Anexos IX, X e XI do MDR quando disponíveis.
- Para Classe IIa, IIb e III, explicar que há envolvimento de organismo notificado quando o contexto o sustentar.
- Para Classe IIb, explicar que o fabricante deve seguir um procedimento de avaliação da conformidade aplicável, como Anexo IX ou combinação Anexo X + Anexo XI, se essas fontes estiverem no contexto.
- Incluir documentação técnica, avaliação clínica, sistema de gestão da qualidade, declaração UE de conformidade e marcação CE apenas se houver fonte no contexto.
- Não transformar perguntas de marcação CE em classificação de risco.
- Não usar capítulos genéricos como fonte principal se houver artigos/anexos específicos disponíveis.
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
- Se a pergunta também perguntar se o produto é dispositivo médico, começa com uma nota curta de qualificação com base no MDR Artigo 2, se estiver no contexto.
- Depois responde à classe MDR com base no MDR Artigo 51 e no MDR Anexo VIII.
- Não assumas automaticamente Classe I só porque o dispositivo é não invasivo.
- Se o dispositivo for ativo, digital, mede/estima parâmetros fisiológicos, apoia diagnóstico ou monitorização clínica, considera primeiro as regras de dispositivos ativos e/ou software antes da Regra 1.
- Para dispositivos ativos destinados a diagnóstico ou monitorização, considera a Regra 10 quando estiver no contexto.
- Para software que presta informações usadas em decisões com fins terapêuticos ou de diagnóstico, considera a Regra 11 quando estiver no contexto.
- Se houver IA, separa sempre a classe MDR da categoria de risco do AI Act.
- Se a classificação depender de finalidade prevista, criticidade da decisão, utilizadores ou impacto clínico, responde com “Classe provável” e lista as condições a confirmar.
- Não uses fontes sobre declaração UE de conformidade, registo, PMS, avaliação da conformidade ou organismos notificados para decidir a classe.
- Se o contexto contiver Regra 10 e o dispositivo for um termómetro digital/ativo destinado a diagnóstico ou monitorização, não respondas apenas "não está claro"; indica "Classe provável: Classe IIa", com condições a confirmar.
- Se o contexto contiver Regra 11 e o software prestar informações usadas para decisões com fins terapêuticos ou de diagnóstico, começa por "Classe provável: Classe IIa".
- Só indiques Classe IIb ou Classe III quando o contexto ou a pergunta indicar impacto clínico grave, intervenção cirúrgica, morte ou deterioração irreversível.
- Nunca apresentes Classe IIb como conclusão direta para software de apoio ao diagnóstico se ainda não estiver confirmada a gravidade da decisão clínica.
- Se a pergunta disser apenas termómetro simples/não invasivo, sem indicar que é digital, ativo, software, IA, infravermelhos ou algoritmo, considera primeiro a Regra 1.
- Para termómetro simples não invasivo, a conclusão esperada é "Classe provável: Classe I", salvo se outra regra do Anexo VIII se aplicar.
- Só aplica Regra 10 ao termómetro quando a pergunta indicar que é ativo, digital, eletrónico, por infravermelhos, software, IA, algoritmo, ou destinado a diagnóstico/monitorização clínica ativa.
""",

    "ai_provider_obligations": """
Objetivo da resposta:
- Responder sobre obrigações do prestador de sistemas de IA de risco elevado segundo o AI Act.
- Priorizar AI_ACT Artigo 16.
- Usar Artigos 9 a 15 apenas quando estiverem no contexto e sustentarem requisitos específicos.
- Não responder com classificação MDR nem com classes MDR.
- Não usar fontes MDR para obrigações do prestador AI Act.
""",

    "ai_high_risk": """
Objetivo da resposta:
- Responder se o sistema de IA é ou pode ser de risco elevado segundo o AI Act.
- Priorizar AI_ACT Artigo 6 e, quando disponível, AI_ACT ANEXO III.
- Se o produto for dispositivo médico com IA, explicar que pode ser de risco elevado conforme o enquadramento do Artigo 6, mas sem inventar detalhes fora do contexto.
- Não responder com Classe I, IIa, IIb ou III do MDR.
- Não usar MDR Anexo VIII para classificar risco AI Act.
""",

    "gspr_requirements": """
Objetivo da resposta:
- Responder sobre os requisitos gerais de segurança e desempenho do MDR.
- Priorizar MDR ANEXO I.
- Organizar por grupos de requisitos quando possível: requisitos gerais, conceção/fabrico, informação fornecida com o dispositivo.
- Não usar Artigo 55, Artigo 57, Anexo VII, Anexo X, Anexo XIII ou Artigo 117 como fontes principais.
""",

    "device_qualification": """
Objetivo da resposta:
- Responder se o produto parece enquadrar-se como dispositivo médico segundo o MDR.
- Priorizar MDR Artigo 2 e MDR (19), quando disponíveis.
- A conclusão deve depender da finalidade prevista pelo fabricante.
- Se for apenas bem-estar, estilo de vida ou hidratação sem finalidade médica específica, dizer que em princípio não é dispositivo médico.
- Se houver finalidade médica específica, como diagnóstico, prevenção, monitorização, previsão, prognóstico, tratamento ou atenuação de doença, explicar que pode ser dispositivo médico.
- Não uses Artigo 10, Anexo XIII, UDI, PMS ou documentação técnica para decidir se algo é dispositivo médico.
- Não digas que o MDR se aplica a animais.
- Não inventes expressões que não estejam no contexto.
- Não faças citações literais entre aspas, a menos que copies exatamente do contexto.
- Evita resposta absoluta quando a finalidade prevista não estiver totalmente definida.
""",

    "clinical_evaluation_terms": """
Objetivo da resposta:
- Explicar claramente a diferença entre avaliação clínica, investigação clínica e PMCF.
- Priorizar MDR Artigo 61 e MDR Anexo XIV.
- Se disponível, usar definições do MDR Artigo 2.
- Não dizer que investigação clínica não existe como termo distinto.
- Explicar PMCF como acompanhamento clínico pós-comercialização, não como 'Post-Comercialização Clinical Evaluation'.
- Organizar a resposta em 3 blocos: avaliação clínica, investigação clínica e PMCF.
""",

"pms_plan": """
Objetivo da resposta:
- Responder apenas sobre o plano de vigilância pós-comercialização/PMS.
- Priorizar MDR Artigo 83, MDR Artigo 84 e MDR ANEXO III.
- Não misturar com PMCF, investigação clínica, SSCP ou avaliação por organismo notificado, salvo se a pergunta pedir essa ligação.
- Organizar a resposta como checklist prática do conteúdo do plano PMS.
- Não usar Artigo 32, Artigo 45, Artigo 55, Artigo 71 ou Artigo 74 como fontes principais.
""",

"pmcf": """
Objetivo da resposta:
- Explicar o que é o PMCF/ACPC e quando entra na avaliação clínica.
- Priorizar MDR Artigo 61 e MDR ANEXO XIV.
- Explicar que o PMCF é acompanhamento clínico pós-comercialização e atualiza a avaliação clínica.
- Não transformar a resposta numa comparação longa com investigação clínica, salvo se o utilizador perguntar por essa diferença.
""",

"classification_and_scope": """
Objetivo da resposta:
- Responder a todas as partes da pergunta: qualificação como dispositivo médico, classe MDR provável e regulamentação/obrigações principais.
- Começar por dizer que a qualificação depende da finalidade prevista pelo fabricante.
- Para a classe MDR, usar MDR Artigo 51, MDR Anexo VIII e a regra aplicável.
- Para dispositivos não invasivos simples, considerar Regra 1 quando estiver no contexto.
- Para dispositivos digitais/ativos destinados a diagnóstico ou monitorização, considerar Regra 10 quando estiver no contexto.
- Para software que presta informações usadas em decisões diagnósticas ou terapêuticas, considerar Regra 11 quando estiver no contexto.
- Depois listar os principais blocos do MDR a cumprir: colocação no mercado, obrigações do fabricante, requisitos gerais de segurança e desempenho, documentação técnica, avaliação clínica, PMS/vigilância pós-comercialização, avaliação da conformidade e marcação CE, apenas quando houver fontes no contexto.
- Só mencionar AI Act se a pergunta mencionar IA, inteligência artificial, algoritmo de IA, machine learning ou sistema de IA.
- Não incluir uma secção sobre IA se a pergunta não falar de IA.
- Terminar com condições a confirmar.
""",

"ai_human_oversight": """
Objetivo da resposta:
- Responder especificamente sobre supervisão humana em sistemas de IA de risco elevado.
- Priorizar AI_ACT Artigo 14.
- Explicar que a supervisão humana serve para prevenir ou minimizar riscos para saúde, segurança e direitos fundamentais.
- Não responder com obrigações genéricas do prestador do Artigo 16, exceto como nota complementar.
- Não falar de classes MDR.
""",

"ai_high_risk_requirements": """
Objetivo da resposta:
- Responder sobre os requisitos que um sistema de IA de risco elevado deve cumprir antes da colocação no mercado.
- Priorizar AI_ACT Artigos 8 a 15.
- Organizar por: gestão de risco, dados/governação, documentação técnica, registos, transparência/instruções, supervisão humana, exatidão/robustez/cibersegurança.
- Pode mencionar obrigações do prestador, avaliação da conformidade e declaração UE de conformidade se AI_ACT Artigo 16, Artigo 43 ou Artigo 47 estiverem no contexto.
- Não misturar com classes MDR.
""",

"pmcf_plan": """
Objetivo da resposta:
- Responder sobre o conteúdo de um plano PMCF/ACPC.
- Priorizar MDR Artigo 61, MDR ANEXO XIV e MDR ANEXO III quando disponíveis.
- Dar uma checklist prática do que o plano deve conter.
- Não iniciar o fluxo de geração de documento.
- Não inventar classe MDR, regra MDR ou categoria AI Act se a pergunta não descrever um dispositivo concreto.
""",

"pms_pmcf_vigilance": """
Objetivo da resposta:
- Explicar a diferença entre PMS, PMCF/ACPC e vigilância.
- PMS: sistema/processo geral de monitorização pós-comercialização.
- PMCF/ACPC: componente clínica pós-comercialização que atualiza a avaliação clínica.
- Vigilância: reporte e gestão de incidentes graves, ações corretivas de segurança e tendências.
- Priorizar MDR Artigo 83, Artigo 84, Anexo III, Artigo 87/88 e Anexo XIV quando disponíveis.
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

    "ai_provider_obligations": 8,
    "ai_high_risk": 6,
    "gspr_requirements": 8,
    "device_qualification": 6,
    "clinical_evaluation_terms": 8,
    "classification_and_scope": 10,
    "pms_plan": 6,
    "pmcf": 6,
    "ai_human_oversight": 6,
    "ai_high_risk_requirements": 8,
    "pmcf_plan": 8,
    "pms_pmcf_vigilance": 8,
}


def embed_query_text(text: str) -> List[float]:
    """
    Gera embedding para uma pergunta usando o mesmo método usado na indexação.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    response = ollama.embed(
        model=OLLAMA_EMBED_MODEL,
        input=text,
    )

    return response["embeddings"][0]


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


def has_mdr_rule(text: str, rule_number: int) -> bool:
    """
    Deteta regras MDR mesmo quando o PDF vem como:
    - Regra 10
    - Regra n.o 10
    - Regra n.º 10
    - Regra no 10
    """
    pattern = rf"\bregra\s+(?:n\.?\s*[ºo°]?\s*)?{rule_number}\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def has_any_mdr_rule(text: str, rule_numbers: List[int]) -> bool:
    return any(has_mdr_rule(text, n) for n in rule_numbers)


def has_generation_citation(
    generation_indices: List[int],
    records: List[Dict[str, Any]],
    citation: str,
) -> bool:
    wanted = citation.strip().lower()

    for idx in generation_indices:
        got = str(records[idx].get("citation_label", "") or "").strip().lower()
        if got == wanted:
            return True

    return False


def answer_mentions_citation(answer: str, citation: str) -> bool:
    """
    Verifica se uma citação aparece realmente na resposta final.
    Isto evita marcar como 'Utilizada' fontes que só foram enviadas ao LLM.
    """
    if not answer or not citation:
        return False

    pattern = re.escape(citation.strip())
    return re.search(pattern, answer, flags=re.IGNORECASE) is not None


def cited_generation_indices(
    answer: str,
    generation_indices: List[int],
    records: List[Dict[str, Any]],
) -> List[int]:
    """
    Mantém apenas as fontes cuja citation_label aparece na resposta final.
    """
    used = []

    for idx in generation_indices:
        citation = str(records[idx].get("citation_label", "") or "").strip()
        if citation and answer_mentions_citation(answer, citation):
            used.append(idx)

    return used

def is_general_manufacturer_obligations_question(question: str) -> bool:
    q = (question or "").lower()

    return (
        "fabricante" in q
        and (
            "obrigações gerais" in q
            or "obrigacoes gerais" in q
            or "que obrigações" in q
            or "que obrigacoes" in q
            or "obrigações tem" in q
            or "obrigacoes tem" in q
        )
        and (
            "mdr" in q
            or "dispositivo médico" in q
            or "dispositivo medico" in q
        )
    )


def build_canonical_manufacturer_obligations_answer(
    *,
    question: str,
    plan: Dict[str, Any],
    generation_indices: List[int],
    records: List[Dict[str, Any]],
) -> Optional[str]:
    if not is_general_manufacturer_obligations_question(question):
        return None

    fixed = build_fixed_regulations_section(plan)

    obligations = []

    if has_generation_citation(generation_indices, records, "MDR Artigo 10"):
        obligations.extend([
            "1. Garantir que o dispositivo é concebido e fabricado em conformidade com os requisitos aplicáveis do MDR. [MDR Artigo 10]",
            "2. Implementar, manter, atualizar e melhorar continuamente um sistema de gestão da qualidade. [MDR Artigo 10]",
            "3. Implementar e manter um sistema de gestão de risco. [MDR Artigo 10]",
            "4. Elaborar e manter a documentação técnica do dispositivo. [MDR Artigo 10]",
            "5. Assegurar procedimentos para manter a conformidade da produção em série. [MDR Artigo 10]",
        ])

    if has_generation_citation(generation_indices, records, "MDR Artigo 61"):
        obligations.append(
            "6. Realizar e manter uma avaliação clínica adequada ao dispositivo. [MDR Artigo 61]"
        )

    if has_generation_citation(generation_indices, records, "MDR Artigo 83"):
        obligations.append(
            "7. Estabelecer, aplicar, documentar e manter um sistema de monitorização pós-comercialização. [MDR Artigo 83]"
        )

    if has_generation_citation(generation_indices, records, "MDR Artigo 15"):
        obligations.append(
            "8. Dispor de uma pessoa responsável pela observância da regulamentação, quando aplicável. [MDR Artigo 15]"
        )

    if has_generation_citation(generation_indices, records, "MDR Artigo 19"):
        obligations.append(
            "9. Elaborar a Declaração UE de Conformidade quando a conformidade tiver sido demonstrada. [MDR Artigo 19]"
        )

    if has_generation_citation(generation_indices, records, "MDR Artigo 27"):
        obligations.append(
            "10. Cumprir os requisitos aplicáveis ao sistema de identificação única dos dispositivos, incluindo UDI. [MDR Artigo 27]"
        )

    obligations = obligations[:10]

    citations = []
    for c in [
        "MDR Artigo 10",
        "MDR Artigo 15",
        "MDR Artigo 19",
        "MDR Artigo 27",
        "MDR Artigo 61",
        "MDR Artigo 83",
    ]:
        if has_generation_citation(generation_indices, records, c):
            citations.append(f"- {c}")

    body = [
        "2. Obrigações gerais do fabricante segundo o MDR",
        *obligations,
        "",
        "3. Citações usadas",
        *citations,
    ]

    return f"{fixed}\n\n" + "\n".join(body).strip()


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


def is_good_ai_provider_obligations_source(record: Dict[str, Any]) -> bool:
    if record.get("short_name") != "AI_ACT":
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    good_patterns = [
        "artigo 16",
        "obrigações dos prestadores",
        "obrigacoes dos prestadores",
        "artigo 9",
        "sistema de gestão de riscos",
        "sistema de gestao de riscos",
        "artigo 10",
        "dados e governação dos dados",
        "dados e governacao dos dados",
        "artigo 11",
        "documentação técnica",
        "documentacao tecnica",
        "artigo 12",
        "conservação de registos",
        "conservacao de registos",
        "artigo 13",
        "transparência",
        "transparencia",
        "artigo 14",
        "supervisão humana",
        "supervisao humana",
        "artigo 15",
        "exatidão",
        "exatidao",
        "robustez",
        "cibersegurança",
        "ciberseguranca",
    ]

    return any(p in text for p in good_patterns)


def is_good_ai_high_risk_source(record: Dict[str, Any]) -> bool:
    if record.get("short_name") != "AI_ACT":
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    good_patterns = [
        "artigo 6",
        "regras para a classificação de sistemas de ia de risco elevado",
        "regras para a classificacao de sistemas de ia de risco elevado",
        "anexo iii",
        "sistemas de ia de risco elevado",
        "artigo 43",
        "avaliação da conformidade",
        "avaliacao da conformidade",
    ]

    return any(p in text for p in good_patterns)


def is_good_gspr_source(record: Dict[str, Any]) -> bool:
    if record.get("short_name") != "MDR":
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    # Para perguntas GSPR, a fonte principal deve ser o Anexo I.
    return re.search(r"\banexo\s+i\b", text) is not None


def is_good_device_qualification_source(record: Dict[str, Any]) -> bool:
    if record.get("short_name") != "MDR":
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    good_patterns = [
        "artigo 2",
        "definições",
        "definicoes",
        "dispositivo médico",
        "dispositivo medico",
        "software",
        "fim médico específico",
        "fim medico especifico",
        "finalidade médica",
        "finalidade medica",
        "considerando (19)",
        "estilo de vida",
        "bem-estar",
    ]

    bad_patterns = [
        "artigo 10",
        "obrigações gerais dos fabricantes",
        "obrigacoes gerais dos fabricantes",
        "anexo xiii",
        "dispositivos feitos por medida",
        "documentação técnica",
        "documentacao tecnica",
        "anexo vi",
        "udi",
    ]

    return any(p in text for p in good_patterns) and not any(p in text for p in bad_patterns)


def is_good_clinical_evaluation_terms_source(record: Dict[str, Any]) -> bool:
    if record.get("short_name") != "MDR":
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    good_patterns = [
        "artigo 2",
        "artigo 61",
        "artigo 62",
        "avaliação clínica",
        "avaliacao clinica",
        "investigação clínica",
        "investigacao clinica",
        "anexo xiv",
        "acompanhamento clínico pós-comercialização",
        "acompanhamento clinico pos-comercializacao",
        "pmcf",
        "evidência clínica",
        "evidencia clinica",
    ]

    bad_patterns = [
        "artigo 45",
        "organismo notificado",
        "anexo vii",
        "anexo xiii",
        "declaração ue de conformidade",
        "declaracao ue de conformidade",
    ]

    return any(p in text for p in good_patterns) and not any(p in text for p in bad_patterns)


def is_good_pms_plan_source(record: Dict[str, Any]) -> bool:
    if record.get("short_name") != "MDR":
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    good_patterns = [
        "artigo 83",
        "sistema de monitorização pós-comercialização",
        "sistema de monitorizacao pos-comercializacao",
        "artigo 84",
        "plano de vigilância pós-comercialização",
        "plano de vigilancia pos-comercializacao",
        "anexo iii",
        "documentação técnica relativa à monitorização pós-comercialização",
        "documentacao tecnica relativa a monitorizacao pos-comercializacao",
    ]

    bad_patterns = [
        "artigo 32",
        "artigo 45",
        "artigo 55",
        "artigo 71",
        "artigo 74",
        "anexo vii",
        "anexo x",
        "anexo xiv",
        "organismo notificado",
        "investigação clínica",
        "investigacao clinica",
    ]

    return any(p in text for p in good_patterns) and not any(p in text for p in bad_patterns)


def is_good_pmcf_source(record: Dict[str, Any]) -> bool:
    if record.get("short_name") != "MDR":
        return False

    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    good_patterns = [
        "artigo 61",
        "anexo xiv",
        "acompanhamento clínico pós-comercialização",
        "acompanhamento clinico pos-comercializacao",
        "pmcf",
        "acpc",
        "avaliação clínica",
        "avaliacao clinica",
    ]

    bad_patterns = [
        "artigo 45",
        "artigo 55",
        "anexo vii",
        "organismo notificado",
        "declaração ue de conformidade",
        "declaracao ue de conformidade",
    ]

    return any(p in text for p in good_patterns) and not any(p in text for p in bad_patterns)

def is_bad_gspr_source(record: Dict[str, Any]) -> bool:
    text = (
        normalized_source_text(record)
        + " "
        + str(record.get("chunk_text", "") or "").lower()
    )

    bad_patterns = [
        "artigo 55",
        "artigo 57",
        "artigo 105",
        "artigo 117",
        "anexo vii",
        "anexo x",
        "anexo xiii",
        "organismos notificados",
        "organismo notificado",
        "mecanismo de escrutínio",
        "mecanismo de escrutinio",
        "alteração da diretiva",
        "alteracao da diretiva",
        "dispositivos feitos por medida",
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
            
        if intent == "classification_and_scope":
            if short_name == "MDR":
                if "artigo 2" in text or "dispositivo médico" in text or "dispositivo medico" in text:
                    p += 0.45

                if "artigo 51" in text or "classificação dos dispositivos" in text or "classificacao dos dispositivos" in text:
                    p += 0.50

                if "anexo viii" in text or "regras de classificação" in text or "regras de classificacao" in text:
                    p += 0.55

                if has_mdr_rule(text, 10):
                    p += 0.70 if plan.get("is_thermometer") else 0.35

                if has_mdr_rule(text, 11):
                    p += 0.70 if plan.get("is_software") else 0.35

                if has_mdr_rule(text, 1):
                    p += 0.40

                if "artigo 5" in text or "colocação no mercado" in text or "colocacao no mercado" in text:
                    p += 0.35

                if "artigo 10" in text or "obrigações gerais dos fabricantes" in text or "obrigacoes gerais dos fabricantes" in text:
                    p += 0.45

                if "anexo i" in text or "requisitos gerais de segurança e desempenho" in text or "requisitos gerais de seguranca e desempenho" in text:
                    p += 0.35

                if "anexo ii" in text or "documentação técnica" in text or "documentacao tecnica" in text:
                    p += 0.30

                if "artigo 61" in text or "avaliação clínica" in text or "avaliacao clinica" in text:
                    p += 0.25

                if "artigo 83" in text or "vigilância pós-comercialização" in text or "vigilancia pos-comercializacao" in text:
                    p += 0.25

                if "artigo 20" in text or "marcação ce" in text or "marcacao ce" in text:
                    p += 0.25

            if short_name == "AI_ACT":
                if plan.get("mentions_ai") and ("artigo 6" in text or "risco elevado" in text or "alto risco" in text):
                    p += 0.45
                elif not plan.get("mentions_ai"):
                    p -= 2.00
        

        elif intent == "classification_risk":
            if "artigo 51" in text or "classificação dos dispositivos" in text or "classificacao dos dispositivos" in text:
                p += 0.50

            if "anexo viii" in text or "regras de classificação" in text or "regras de classificacao" in text:
                p += 0.55
                
            if has_mdr_rule(text, 5):
                p += 1.20 if plan.get("is_urinary_catheter") else 0.20

            if has_mdr_rule(text, 8):
                p += 1.20 if plan.get("is_orthopedic_implant") else 0.20

            if has_mdr_rule(text, 10):
                if plan.get("is_cardiac_monitoring"):
                    p += 1.20
                elif plan.get("is_active_or_digital_thermometer"):
                    p += 0.95
                elif plan.get("is_simple_thermometer"):
                    p -= 0.35
                else:
                    p += 0.45
                
            if "regra 11" in text:
                p += 0.95 if (plan.get("is_software") or plan.get("mentions_ai")) else 0.45

            if has_mdr_rule(text, 11):
                p += 0.95 if (plan.get("is_software") or plan.get("mentions_ai")) else 0.45

            if has_mdr_rule(text, 1):
                if plan.get("is_simple_thermometer"):
                    p += 0.95
                elif plan.get("is_thermometer") and not plan.get("is_active_or_digital_thermometer"):
                    p += 0.70
                elif plan.get("is_software") or plan.get("mentions_ai"):
                    p += 0.10
                else:
                    p += 0.55

            if has_any_mdr_rule(text, [2, 3, 4]):
                p += 0.25

            if "não invasivo" in text or "nao invasivo" in text:
                if plan.get("is_thermometer") or plan.get("is_software") or plan.get("mentions_ai"):
                    p += 0.10
                else:
                    p += 0.35

            if "medição" in text or "medicao" in text or "temperatura" in text or "termómetro" in text or "termometro" in text:
                p += 0.45

            if is_bad_for_classification(idx):
                p -= 1.50

        
        elif intent == "ai_provider_obligations":
            if short_name == "AI_ACT":
                p += 0.30

            if "artigo 16" in text or "obrigações dos prestadores" in text or "obrigacoes dos prestadores" in text:
                p += 0.90

            if any(x in text for x in ["artigo 9", "artigo 10", "artigo 11", "artigo 12", "artigo 13", "artigo 14", "artigo 15"]):
                p += 0.35

            if short_name != "AI_ACT":
                p -= 2.00


        elif intent == "ai_high_risk":
            if short_name == "AI_ACT":
                p += 0.30

            if "artigo 6" in text or "risco elevado" in text or "alto risco" in text:
                p += 0.90

            if "anexo iii" in text:
                p += 0.55

            if "artigo 43" in text or "avaliação da conformidade" in text or "avaliacao da conformidade" in text:
                p += 0.25

            if short_name != "AI_ACT":
                p -= 2.00


        elif intent == "gspr_requirements":
            if short_name == "MDR":
                p += 0.30

            if "anexo i" in text or "requisitos gerais de segurança e desempenho" in text or "requisitos gerais de seguranca e desempenho" in text:
                p += 1.00

            if is_bad_gspr_source(r):
                p -= 2.00
        
        
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
        
        if intent == "classification_and_scope":
            if r.get("short_name") == "AI_ACT":
                if plan.get("mentions_ai") and is_good_ai_high_risk_source(r):
                    pass
                else:
                    return False
            else:
                if (
                    is_good_classification_source(r)
                    or is_good_device_qualification_source(r)
                    or is_good_regulatory_scope_source(r)
                    or is_good_manufacturer_obligations_source(r)
                    or is_good_gspr_source(r)
                ):
                    pass
                else:
                    return False
                

        elif intent == "classification_risk":
            if r.get("short_name") == "AI_ACT":
                if plan.get("mentions_ai") and is_good_ai_high_risk_source(r):
                    pass
                else:
                    return False

            else:
                if is_bad_for_classification(idx):
                    return False

                if is_good_classification_source(r):
                    pass
                elif plan.get("asks_hybrid_device_and_classification") and is_good_device_qualification_source(r):
                    pass
                else:
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
            
        if intent == "ai_provider_obligations":
            if not is_good_ai_provider_obligations_source(r):
                return False

        if intent == "ai_high_risk":
            if not is_good_ai_high_risk_source(r):
                return False

        if intent == "gspr_requirements":
            if is_bad_gspr_source(r):
                return False
            if not is_good_gspr_source(r):
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
    if intent == "ai_provider_obligations":
        for wanted in [
            "artigo 16",
            "artigo 9",
            "artigo 10",
            "artigo 11",
            "artigo 12",
            "artigo 13",
            "artigo 14",
            "artigo 15",
        ]:
            add_best_match([
                lambda r, text, wanted=wanted: r.get("short_name") == "AI_ACT",
                lambda r, text, wanted=wanted: wanted in text,
            ])


    elif intent == "ai_high_risk":
        for wanted in [
            "artigo 6",
            "anexo iii",
            "artigo 43",
        ]:
            add_best_match([
                lambda r, text, wanted=wanted: r.get("short_name") == "AI_ACT",
                lambda r, text, wanted=wanted: wanted in text,
            ])


    elif intent == "gspr_requirements":
        add_best_match([
            lambda r, text: r.get("short_name") == "MDR",
            lambda r, text: "anexo i" in text or "requisitos gerais de segurança e desempenho" in text or "requisitos gerais de seguranca e desempenho" in text,
        ])
    
    
    elif intent == "manufacturer_obligations":
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
    
    
    elif intent == "classification_and_scope":
        wanted_terms = [
            "artigo 2",
            "artigo 51",
            "anexo viii",
            "artigo 5",
            "artigo 10",
            "anexo i",
            "anexo ii",
            "artigo 61",
            "artigo 83",
            "artigo 20",
        ]

        if plan.get("is_urinary_catheter"):
            wanted_terms.insert(3, "regra 5")
        elif plan.get("is_orthopedic_implant"):
            wanted_terms.insert(3, "regra 8")
        elif plan.get("is_cardiac_monitoring"):
            wanted_terms.insert(3, "regra 10")
        elif plan.get("is_thermometer"):
            wanted_terms.insert(3, "regra 10")
        elif plan.get("is_software"):
            wanted_terms.insert(3, "regra 11")
        else:
            wanted_terms.insert(3, "regra 1")

        if plan.get("mentions_ai"):
            wanted_terms.extend(["artigo 6", "anexo iii"])

        for wanted in wanted_terms:
            add_best_match([
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

        if plan.get("is_urinary_catheter"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 5),
            ])

        elif plan.get("is_orthopedic_implant"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 8),
            ])

        elif plan.get("is_cardiac_monitoring"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 10),
            ])

        elif plan.get("is_wound_dressing"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 4),
            ])

        elif plan.get("is_drug_administration"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 12),
            ])

        elif plan.get("is_insulin_dose_software"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 11),
            ])
        
        elif plan.get("is_simple_thermometer"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 1) or "não invasivo" in text or "nao invasivo" in text,
            ])

        elif plan.get("is_active_or_digital_thermometer"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 10),
            ])

        elif plan.get("is_software") or plan.get("mentions_ai"):
            add_best_match([
                lambda r, text: r.get("short_name") == "MDR",
                lambda r, text: has_mdr_rule(text, 11),
            ])

        else:
            for rule_no in [1, 4, 5, 8, 10, 11, 12]:
                add_best_match([
                    lambda r, text: r.get("short_name") == "MDR",
                    lambda r, text, rule_no=rule_no: has_mdr_rule(text, rule_no),
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


def is_explicit_follow_up_question(question: str) -> bool:
    """
    Deteta apenas follow-ups explícitas.

    Importante:
    - Não usar comprimento da pergunta.
    - Perguntas curtas podem ser perguntas independentes.
    - O histórico só deve entrar quando o utilizador referencia claramente
      algo anterior.
    """
    q = (question or "").strip().lower()

    follow_up_markers = [
        "em relação à pergunta anterior",
        "em relacao a pergunta anterior",
        "em relação à resposta anterior",
        "em relacao a resposta anterior",
        "em relação à primeira pergunta",
        "em relacao a primeira pergunta",
        "em relação à segunda pergunta",
        "em relacao a segunda pergunta",
        "em relação à terceira pergunta",
        "em relacao a terceira pergunta",
        "como disse antes",
        "como referido antes",
        "como falámos",
        "como falamos",
        "o dispositivo anterior",
        "a app anterior",
        "o software anterior",
        "esse dispositivo",
        "essa app",
        "esse software",
        "esse sistema",
        "este dispositivo",
        "esta app",
        "este software",
        "este sistema",
        "o mesmo dispositivo",
        "a mesma app",
        "o mesmo software",
        "o mesmo sistema",
        "nesse caso",
        "neste caso",
        "com base nisso",
        "com base na resposta anterior",
        "com base na análise anterior",
        "com base na analise anterior",
        "faz o documento",
        "gera o documento",
        "cria o documento",
        "gera o pmcf",
        "faz o pmcf",
        "faz agora o documento pmcf",
    ]

    return any(marker in q for marker in follow_up_markers)


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
- Organiza a resposta por passos numerados.
- Para um dispositivo Classe IIb, explica que o fabricante deve realizar avaliação da conformidade segundo o MDR Artigo 52.
- Usa MDR ANEXO IX para o caminho baseado no sistema de gestão da qualidade e avaliação da documentação técnica, se estiver no contexto.
- Usa MDR ANEXO X e MDR ANEXO XI como alternativa quando estiverem no contexto.
- Inclui Declaração UE de Conformidade e marcação CE no fim do processo, se as fontes estiverem no contexto.
- Evita usar MDR CAPÍTULO V como citação principal quando houver MDR Artigo 52, MDR ANEXO IX, MDR ANEXO X, MDR ANEXO XI, MDR Artigo 20 ou MDR ANEXO IV.
- Quando explicares alternativas entre Anexo IX e Anexo X + Anexo XI, cita MDR Artigo 52 para a existência das alternativas.
- Cita MDR ANEXO IX apenas para o caminho baseado no sistema de gestão da qualidade e avaliação da documentação técnica.
- Cita MDR ANEXO X apenas para exame de tipo.
- Cita MDR ANEXO XI apenas para verificação da conformidade do produto.
- Nunca digas que a alternativa Anexo X + Anexo XI está detalhada no MDR ANEXO IX.
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
- Não assumas automaticamente Classe I só porque o dispositivo é não invasivo; mas, se for um dispositivo simples não invasivo e não houver sinais de dispositivo ativo/software/IA, considera a Regra 1 como ponto de partida.
- Se o dispositivo for ativo, digital, mede/estima parâmetros fisiológicos, apoia diagnóstico ou monitorização clínica, considera primeiro as regras de dispositivos ativos e/ou software antes da Regra 1.
- Para software que presta informações usadas em decisões com fins terapêuticos ou de diagnóstico, considera a Regra 11 quando estiver no contexto.
- Para dispositivos ativos destinados a diagnóstico ou monitorização, considera a Regra 10 quando estiver no contexto.
- Se houver IA, separa sempre a classe MDR da categoria de risco do AI Act.
- A conclusão deve ser condicional quando faltarem finalidade prevista, utilizadores, criticidade da decisão ou impacto clínico.
- Se a pergunta mencionar termómetro digital ativo, diagnóstico direto, monitorização ou parâmetros fisiológicos vitais, considera também a Regra 10 e explica que a classe pode mudar conforme a finalidade concreta.
- Não uses fontes sobre documentação técnica, declaração UE de conformidade, registo, EUDAMED, avaliação da conformidade, organismos notificados ou considerandos para decidir a classe.
- Termina com uma conclusão prática curta: "Classe provável: ...", seguida das condições a confirmar.
- Evita respostas vagas como "não está claro" quando existir Regra 10 ou Regra 11 no contexto.
- Para termómetro digital/ativo com diagnóstico ou monitorização: "Classe provável: Classe IIa", a confirmar pela finalidade prevista.
- Para software de apoio ao diagnóstico: "Classe provável: Classe IIa", podendo subir para IIb/III conforme impacto clínico.
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
- Sistema de vigilância/monitorização pós-comercialização deve ser citado com MDR Artigo 83, não MDR Artigo 61.
- Avaliação clínica deve ser citada com MDR Artigo 61.
- UDI / identificação única do dispositivo deve ser citado com MDR Artigo 27 quando essa fonte estiver no contexto.
- Registo dos dispositivos deve ser citado com MDR Artigo 29.
- Declaração UE de conformidade deve ser citada com MDR Artigo 19; usa MDR ANEXO IV apenas para o conteúdo da declaração.
- Não repitas a mesma obrigação com palavras diferentes.
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
"ai_provider_obligations": """
Instruções adicionais:
- Responde apenas sobre obrigações do prestador segundo o AI Act.
- Prioriza AI_ACT Artigo 16.
- Podes usar AI_ACT Artigos 9 a 15 para detalhar requisitos de sistemas de IA de risco elevado se estiverem no contexto.
- Não respondas com classe MDR.
- Não uses MDR Anexo VIII.
- Cada obrigação deve terminar com a citação correta.
""",

"ai_high_risk": """
Instruções adicionais:
- Responde sobre risco elevado segundo o AI Act, não sobre classe de risco MDR.
- Prioriza AI_ACT Artigo 6 e AI_ACT ANEXO III quando disponíveis.
- Se a resposta depender da finalidade do sistema de IA ou da sua integração como componente de segurança/produto regulado, diz isso claramente.
- Nunca concluas "Classe I", "Classe IIa", "Classe IIb" ou "Classe III", porque isso pertence ao MDR e não ao AI Act.
""",

"gspr_requirements": """
Instruções adicionais:
- Responde sobre requisitos gerais de segurança e desempenho do MDR.
- Usa MDR ANEXO I como fonte principal.
- Organiza a resposta em categorias práticas.
- Não uses fontes de organismos notificados, avaliação da conformidade, dispositivos feitos por medida ou alteração de diretivas.
""",

"device_qualification": """
Instruções adicionais:
- Decide primeiro com base na finalidade prevista pelo fabricante.
- Se o produto tiver finalidade médica específica, como diagnóstico, prevenção, monitorização, previsão, prognóstico, tratamento ou atenuação de doença, diz que pode enquadrar-se como dispositivo médico.
- Se for apenas bem-estar, estilo de vida ou hidratação geral sem finalidade médica específica, diz que em princípio não é dispositivo médico.
- Usa MDR Artigo 2 para a definição.
- Usa MDR (19) apenas para distinguir software médico de software de uso geral/bem-estar.
- Não cites Artigo 10, Anexo XIII, UDI, PMS ou documentação técnica para decidir se algo é dispositivo médico.
- Não digas que o MDR se aplica a animais.
- Não uses aspas para frases que não sejam transcrições exatas do contexto.
""",

"clinical_evaluation_terms": """
Instruções adicionais:
- Organiza a resposta em 3 blocos: avaliação clínica, investigação clínica e PMCF.
- Explica que avaliação clínica é o processo de avaliar dados clínicos para demonstrar segurança e desempenho.
- Explica que investigação clínica é uma investigação realizada para demonstrar a conformidade do dispositivo quando aplicável.
- Explica PMCF como acompanhamento clínico pós-comercialização.
- Não digas que investigação clínica não é termo distinto.
- Não traduzas PMCF como “Post-Comercialização Clinical Evaluation”.
- Usa apenas as citações recuperadas no contexto.
""",

"pms_plan": """
Instruções adicionais:
- Responde sobre o plano PMS/vigilância pós-comercialização.
- Usa MDR Artigo 83, MDR Artigo 84 e MDR ANEXO III quando estiverem no contexto.
- Não uses Artigo 32, Artigo 45, Artigo 55, Artigo 71 ou Artigo 74.
- Não confundas PMS com PMCF; podes mencionar PMCF apenas como possível entrada/ligação se estiver no contexto.
""",

"pmcf": """
Instruções adicionais:
- Explica PMCF como acompanhamento clínico pós-comercialização.
- Diz quando deve ser incluído/considerado na avaliação clínica.
- Usa MDR Artigo 61 e MDR ANEXO XIV quando estiverem no contexto.
- Não faças uma resposta longa sobre investigação clínica salvo se a pergunta pedir comparação.
""",

"classification_and_scope": """
Instruções adicionais:
- Responde a todas as subperguntas do utilizador.
- Se a pergunta pedir classe MDR e regulamentação aplicável, responde às duas.
- Primeiro explica se o produto pode ser dispositivo médico, com base na finalidade prevista.
- Depois indica a classe MDR provável com base no MDR Artigo 51, MDR Anexo VIII e na regra aplicável.
- Para dispositivos não invasivos simples, considera Regra 1 quando estiver no contexto.
- Para dispositivos digitais/ativos destinados a diagnóstico ou monitorização, considera Regra 10 quando estiver no contexto.
- Para software que presta informações usadas em decisões de diagnóstico ou terapêuticas, considera Regra 11 quando estiver no contexto.
- Depois lista os principais blocos regulatórios a cumprir: obrigações do fabricante, requisitos gerais de segurança e desempenho, documentação técnica, avaliação clínica, PMS/vigilância pós-comercialização, avaliação da conformidade e marcação CE, apenas quando existirem fontes no contexto.
- Só menciones AI Act se a pergunta atual mencionar IA, inteligência artificial, algoritmo de IA, machine learning ou sistema de IA.
- Não cries uma secção sobre IA se a pergunta não falar de IA.
- Termina com condições a confirmar.
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
- Responde a todas as subperguntas do utilizador; se a pergunta pedir classe e regulamentação, responde às duas.
- Quando fizeres uma afirmação normativa, associa-a à citação correta usando exatamente o campo "Citação:".
- Nunca escrevas "FONTE 1", "FONTE 2", "FONTE 3" ou semelhante na resposta final.
- Não cries uma nova secção 1.
- Só menciones IA ou AI Act se a pergunta atual mencionar IA, inteligência artificial, algoritmo de IA, machine learning ou sistema de IA.
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
    
    # Remove linhas soltas de contexto normativo que o modelo às vezes copia
    # sem transformar em resposta útil.
    cleaned = re.sub(
        r"(?mi)^\s*Artigo\s+\d+\s+[^.\n]*(?:\n|$)",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?mi)^\s*ANEXO\s+[IVXLC]+\s+[^.\n]*(?:\n|$)",
        "",
        cleaned,
    )
    
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


def improve_answer_if_needed(
    question: str,
    answer: str,
    generation_indices: List[int],
    records: List[Dict[str, Any]],
    plan: Dict[str, Any],
) -> str:
    """
    Pequena camada de segurança para corrigir respostas vagas ou citações trocadas
    em casos recorrentes.
    """
    q = (question or "").lower()
    a = answer or ""

    context_text = " ".join(
        str(records[idx].get("chunk_text", "") or "").lower()
        for idx in generation_indices
    )

    def has_rule(rule_number: int) -> bool:
        return re.search(
            rf"\bregra\s+(?:n\.?\s*[ºo°]?\s*)?{rule_number}\b",
            context_text,
            flags=re.IGNORECASE,
        ) is not None

    if plan.get("intent") == "classification_risk":
        has_rule_10 = has_rule(10)
        has_rule_11 = has_rule(11)

        is_thermometer = (
            "termómetro" in q
            or "termometro" in q
            or "temperatura" in q
        )

        is_software_diag = (
            "software" in q
            and (
                "diagnóstico" in q
                or "diagnostico" in q
                or "radiografia" in q
                or "radiografias" in q
                or "pneumonia" in q
            )
        )

        vague_answer = any(x in a.lower() for x in [
            "não está claro",
            "nao esta claro",
            "não é possível determinar",
            "nao e possivel determinar",
            "classe provável: não",
            "classe provavel: nao",
        ])

        if is_thermometer and has_rule_10 and vague_answer:
            return a.strip() + (
                "\n\nConclusão prática: Classe provável: Classe IIa, a confirmar conforme a finalidade prevista. "
                "A Regra 10 é relevante quando o dispositivo ativo se destina a diagnóstico ou monitorização. "
                "Se a função de IA/software prestar informações usadas em decisões diagnósticas ou terapêuticas, "
                "a Regra 11 também deve ser avaliada. Se a finalidade for apenas bem-estar sem finalidade médica, "
                "a qualificação como dispositivo médico pode mudar."
            )

        if is_software_diag and has_rule_11 and "classe iib" in a.lower() and "classe iia" not in a.lower():
            return a.strip() + (
                "\n\nNota de cautela: pela Regra 11, o ponto de partida para software que presta informações "
                "usadas em decisões com fins diagnósticos ou terapêuticos é Classe IIa. A classificação pode subir "
                "para Classe IIb ou Classe III se a decisão puder causar deterioração grave, intervenção cirúrgica, "
                "morte ou deterioração irreversível. Assim, para apoio ao diagnóstico de pneumonia em radiografias, "
                "a resposta deve ser apresentada como Classe provável IIa, podendo subir conforme o impacto clínico "
                "e a finalidade prevista."
            )

    if plan.get("intent") == "manufacturer_obligations":
        a = re.sub(
            r"(sistema de (?:monitorização|monitorizacao|vigilância|vigilancia) pós-comercialização[^.\n]*?)MDR Artigo 61",
            r"\1MDR Artigo 83",
            a,
            flags=re.IGNORECASE,
        )
        a = re.sub(
            r"(UDI|identificação única do dispositivo|identificacao unica do dispositivo)([^.\n]*?)MDR Artigo 29",
            r"\1\2MDR Artigo 27",
            a,
            flags=re.IGNORECASE,
        )   
        
    a = a.replace("(UID)", "(UDI)")
    a = a.replace(" UID", " UDI")

    return a


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

    if re.search(r"\bregra\s+(?:n\.?\s*[ºo°]?\s*)?\d+\b", text):
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
        r"\bartigo\s+123\b",
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
        "entrada em vigor",
        "data de aplicação",
        "data de aplicacao",
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

    if re.search(r"\bregra\s+(?:n\.?\s*[ºo°]?\s*)?\d+\b", text):
        return True
    
    if has_any_mdr_rule(text, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 22]):
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
    
    
    if intent == "ai_provider_obligations":
        ai_ranked = [
            idx for idx in ranked
            if is_good_ai_provider_obligations_source(records[idx])
        ]

        for wanted in [
            "artigo 16",
            "artigo 9",
            "artigo 10",
            "artigo 11",
            "artigo 12",
            "artigo 13",
            "artigo 14",
            "artigo 15",
        ]:
            for idx in ai_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in ai_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]


    if intent == "ai_high_risk":
        ai_ranked = [
            idx for idx in ranked
            if is_good_ai_high_risk_source(records[idx])
        ]

        for wanted in [
            "artigo 6",
            "anexo iii",
            "artigo 43",
        ]:
            for idx in ai_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in ai_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]


    if intent == "gspr_requirements":
        gspr_ranked = [
            idx for idx in ranked
            if is_good_gspr_source(records[idx])
            and not is_bad_gspr_source(records[idx])
        ]

        for idx in gspr_ranked:
            t = source_text(idx)
            if "anexo i" in t or "requisitos gerais de segurança e desempenho" in t or "requisitos gerais de seguranca e desempenho" in t:
                add(idx)

        for idx in gspr_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]
    
        
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

    if intent == "device_qualification":
        qual_ranked = [
            idx for idx in ranked
            if is_good_device_qualification_source(records[idx])
        ]

        for wanted in ["artigo 2", "considerando (19)", "software", "bem-estar", "estilo de vida"]:
            for idx in qual_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in qual_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]


    if intent == "clinical_evaluation_terms":
        clinical_ranked = [
            idx for idx in ranked
            if is_good_clinical_evaluation_terms_source(records[idx])
        ]

        for wanted in ["artigo 2", "artigo 61", "artigo 62", "anexo xiv", "pmcf"]:
            for idx in clinical_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in clinical_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]
    
    if intent == "pms_plan":
        pms_ranked = [
            idx for idx in ranked
            if is_good_pms_plan_source(records[idx])
        ]

        for wanted in ["artigo 83", "artigo 84", "anexo iii"]:
            for idx in pms_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in pms_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]


    if intent == "pmcf":
        pmcf_ranked = [
            idx for idx in ranked
            if is_good_pmcf_source(records[idx])
        ]

        for wanted in ["artigo 61", "anexo xiv", "pmcf", "acompanhamento"]:
            for idx in pmcf_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in pmcf_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]

    if intent == "classification_and_scope":
        hybrid_ranked = [
            idx for idx in ranked
            if (
                is_good_classification_source(records[idx])
                or is_good_device_qualification_source(records[idx])
                or is_good_regulatory_scope_source(records[idx])
                or is_good_manufacturer_obligations_source(records[idx])
                or is_good_gspr_source(records[idx])
                or (
                    plan.get("mentions_ai")
                    and is_good_ai_high_risk_source(records[idx])
                )
            )
        ]

        wanted_terms = [
            "artigo 2",
            "artigo 51",
            "anexo viii",
            "artigo 5",
            "artigo 10",
            "anexo i",
            "anexo ii",
            "artigo 61",
            "artigo 83",
            "artigo 20",
        ]

        if plan.get("is_urinary_catheter"):
            wanted_terms.insert(3, "regra 5")
        elif plan.get("is_orthopedic_implant"):
            wanted_terms.insert(3, "regra 8")
        elif plan.get("is_cardiac_monitoring"):
            wanted_terms.insert(3, "regra 10")
        elif plan.get("is_thermometer"):
            wanted_terms.insert(3, "regra 10")
        elif plan.get("is_software"):
            wanted_terms.insert(3, "regra 11")
        else:
            wanted_terms.insert(3, "regra 1")

        if plan.get("mentions_ai"):
            wanted_terms.extend(["artigo 6", "anexo iii"])

        for wanted in wanted_terms:
            for idx in hybrid_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in hybrid_ranked:
            if len(selected) >= max_items:
                break
            add(idx)

        return selected[:max_items]
    
    
    elif intent == "classification_risk":
        classification_ranked = [
            idx for idx in ranked
            if is_good_classification_source(records[idx])
            or (
                plan.get("asks_hybrid_device_and_classification")
                and is_good_device_qualification_source(records[idx])
            )
            or (
                plan.get("mentions_ai")
                and is_good_ai_high_risk_source(records[idx])
            )
        ]

        # Se também pergunta se é dispositivo médico, trazer Artigo 2 / Considerando 19.
        if plan.get("asks_hybrid_device_and_classification"):
            for wanted in ["artigo 2", "considerando (19)"]:
                for idx in classification_ranked:
                    t = source_text(idx)
                    if wanted in t:
                        add(idx)
                        break

        # Base legal geral da classificação MDR.
        for idx in classification_ranked:
            t = source_text(idx)
            if "artigo 51" in t or "classificação dos dispositivos" in t or "classificacao dos dispositivos" in t:
                add(idx)
                break

        # Anexo VIII.
        for idx in classification_ranked:
            t = source_text(idx)
            if "anexo viii" in t and ("regras de classificação" in t or "regras de classificacao" in t):
                add(idx)
                break

        # Regras por família de dispositivo.
        if plan.get("is_urinary_catheter"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 5):
                    add(idx)
                    break

        elif plan.get("is_orthopedic_implant"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 8):
                    add(idx)
                    break

        elif plan.get("is_cardiac_monitoring"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 10):
                    add(idx)
                    break
        
        elif plan.get("is_wound_dressing"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 4):
                    add(idx)
                    break

        elif plan.get("is_drug_administration"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 12):
                    add(idx)
                    break

        elif plan.get("is_insulin_dose_software"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 11):
                    add(idx)
                    break
        
        elif plan.get("is_simple_thermometer"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 1) or "não invasivo" in t or "nao invasivo" in t:
                    add(idx)
                    break

        elif plan.get("is_active_or_digital_thermometer"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 10):
                    add(idx)
                    break

        elif plan.get("is_software") or plan.get("mentions_ai"):
            for idx in classification_ranked:
                t = source_text(idx)
                if has_mdr_rule(t, 11):
                    add(idx)
                    break

        else:
            for rule_no in [1, 4, 5, 8, 10, 11, 12]:
                for idx in classification_ranked:
                    t = source_text(idx)
                    if has_mdr_rule(t, rule_no):
                        add(idx)
                        break

        # AI Act separado da classe MDR.
        if plan.get("mentions_ai"):
            for wanted in ["artigo 6", "anexo iii"]:
                for idx in classification_ranked:
                    t = source_text(idx)
                    if records[idx].get("short_name") == "AI_ACT" and wanted in t:
                        add(idx)
                        break

        return selected[:max_items]
    
    
    if intent == "conformity_procedure":
        conformity_ranked = []

        for idx in ranked:
            t = source_text(idx)
            section_type = (records[idx].get("section_type") or "").lower()

            # Evitar CAPÍTULO V quando existem fontes específicas.
            if section_type == "chapter":
                continue

            if any(p in t for p in [
                "artigo 52",
                "avaliação da conformidade",
                "avaliacao da conformidade",
                "anexo ix",
                "anexo x",
                "anexo xi",
                "organismo notificado",
                "marcação ce",
                "marcacao ce",
                "artigo 20",
                "declaração ue de conformidade",
                "declaracao ue de conformidade",
                "anexo iv",
            ]):
                conformity_ranked.append(idx)

        for wanted in [
            "artigo 52",
            "anexo ix",
            "anexo x",
            "anexo xi",
            "organismo notificado",
            "artigo 20",
            "anexo iv",
            "declaração ue de conformidade",
            "declaracao ue de conformidade",
            "marcação ce",
            "marcacao ce",
        ]:
            for idx in conformity_ranked:
                t = source_text(idx)
                if wanted in t:
                    add(idx)
                    break

        for idx in conformity_ranked:
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

    Regra importante:
    - O intent/plano é sempre calculado pela pergunta atual.
    - O histórico só entra no retrieval se a pergunta for follow-up explícita.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    question_clean = (question or "").strip()
    if not question_clean:
        raise ValueError("A pergunta não pode estar vazia.")

    is_follow_up = is_explicit_follow_up_question(question_clean)

    # O plano tem de ser SEMPRE calculado pela pergunta atual,
    # para evitar contaminação pelo histórico.
    plan = analyze_question(question_clean)

    retrieval_question = (
        build_contextual_question(question_clean, history)
        if is_follow_up and history
        else question_clean
    )

    if VECTOR_STORE == "chroma" and chroma_has_documents():
        records, base_scores, adjusted_scores, selected_indices = query_chroma_with_variants(
            retrieval_question,
            plan,
            n_results_per_query=10,
        )

        if plan.get("intent") in {
            "manufacturer_obligations",
            "classification_risk",
            "documentation",
            "document_generation",
            "ai_provider_obligations",
            "ai_high_risk",
            "gspr_requirements",
            "conformity_procedure",
            "device_qualification",
            "clinical_evaluation_terms",
            "classification_and_scope",
            "pms_plan",
            "pmcf",
        }:
            retrieval_max_items = 18

            if plan.get("intent") == "classification_risk":
                retrieval_max_items = 10
            elif plan.get("intent") == "classification_and_scope":
                retrieval_max_items = 14

            selected_indices = select_chroma_retrieved_indices(
                records=records,
                adjusted_scores=adjusted_scores,
                plan=plan,
                max_items=retrieval_max_items,
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

    selected_indices, base_scores, adjusted_scores, _retrieval_plan = retrieve_relevant_indices(
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


def source_text_for_indices(
    generation_indices: List[int],
    records: List[Dict[str, Any]],
) -> str:
    return " ".join(
        str(records[idx].get("chunk_text", "") or "").lower()
        for idx in generation_indices
    )


def citation_for_matching_text(
    generation_indices: List[int],
    records: List[Dict[str, Any]],
    patterns: List[str],
) -> Optional[str]:
    for idx in generation_indices:
        r = records[idx]
        text = " ".join([
            str(r.get("citation_label", "")),
            str(r.get("section_number", "")),
            str(r.get("section_title", "")),
            str(r.get("chunk_text", "")),
        ]).lower()

        if any(p.lower() in text for p in patterns):
            citation = str(r.get("citation_label", "") or "").strip()
            if citation:
                return citation

    return None


def source_contains_rule(
    generation_indices: List[int],
    records: List[Dict[str, Any]],
    rule_number: int,
) -> bool:
    pattern = rf"\bregra\s+(?:n\.?\s*[ºo°]?\s*)?{rule_number}\b"
    text = source_text_for_indices(generation_indices, records)
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def build_canonical_classification_answer(
    *,
    question: str,
    plan: Dict[str, Any],
    generation_indices: List[int],
    records: List[Dict[str, Any]],
) -> Optional[str]:
    if plan.get("intent") != "classification_risk":
        return None

    q = (question or "").lower()
    fixed = build_fixed_regulations_section(plan)

    def cite(c: Optional[str]) -> str:
        return f" [{c}]" if c else ""

    def citations_block(citations: List[Optional[str]]) -> List[str]:
        used = [c for c in dict.fromkeys(citations) if c]
        if not used:
            return []
        return ["", "4. Citações usadas", *[f"- {c}" for c in used]]

    art2 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 2", "definições", "dispositivo médico", "dispositivo medico"],
    )
    art51 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 51", "classificação dos dispositivos", "classificacao dos dispositivos"],
    )
    annex8 = citation_for_matching_text(
        generation_indices,
        records,
        ["anexo viii", "regras de classificação", "regras de classificacao"],
    )
    rule1 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 1", "regra n.º 1", "regra 1", "todos os dispositivos não invasivos", "todos os dispositivos nao invasivos"],
    )
    rule4 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 4", "regra n.º 4", "regra 4", "pele lesada", "membrana mucosa lesada", "exsudados", "feridas"],
    )
    rule5 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 5", "regra n.º 5", "regra 5", "orifícios corporais", "orificios corporais"],
    )
    rule8 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 8", "regra n.º 8", "regra 8", "dispositivos implantáveis", "dispositivos implantaveis"],
    )
    rule10 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 10", "regra n.º 10", "regra 10", "ritmo cardíaco", "ritmo cardiaco", "processos fisiológicos vitais"],
    )
    rule11 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 11", "regra n.º 11", "regra 11", "software destinado a prestar informações"],
    )
    rule12 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 12", "regra n.º 12", "regra 12", "administrar medicamentos", "administração de medicamentos", "administracao de medicamentos", "fluidos corporais", "outras substâncias", "outras substancias"],
    )
    ai6 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 6", "risco elevado", "alto risco"],
    )

    is_urinary_catheter = any(x in q for x in [
        "cateter urinário", "cateter urinario", "cateter uretral", "cateter vesical",
        "sonda urinária", "sonda urinaria", "sonda vesical",
    ])

    is_orthopedic_implant = any(x in q for x in [
        "implante ortopédico", "implante ortopedico", "ortopédico", "ortopedico",
        "prótese", "protese", "implante permanente",
    ])

    is_cardiac_monitoring = any(x in q for x in [
        "ritmo cardíaco", "ritmo cardiaco", "frequência cardíaca", "frequencia cardiaca",
        "ecg", "arritmia", "arritmias", "fibrilhação", "fibrilhacao",
        "fibrilação", "fibrilacao",
    ])

    is_high_acuity = any(x in q for x in [
        "perigo imediato", "perigosa", "perigosas", "alerta", "alertas",
        "urgente", "crítico", "critico",
    ])

    is_thermometer = any(x in q for x in ["termómetro", "termometro", "temperatura"])
    is_active_or_digital_thermometer = is_thermometer and any(x in q for x in [
        "digital", "eletrónico", "eletronico", "electrónico", "electronico",
        "ativo", "activa", "ativa", "infravermelhos", "infra-vermelhos",
        "sensor", "algoritmo", "software", "ia", "inteligência artificial",
        "inteligencia artificial", "machine learning",
    ])

    is_simple_thermometer = is_thermometer and not is_active_or_digital_thermometer
    
    is_wound_dressing = bool(plan.get("is_wound_dressing")) or any(x in q for x in [
        "compressa",
        "penso",
        "curativo",
        "ferida",
        "feridas",
        "exsudado",
        "exsudados",
    ])

    is_superficial_wound_dressing = bool(plan.get("is_superficial_wound_dressing")) or any(x in q for x in [
        "ferida superficial",
        "feridas superficiais",
        "superficial",
        "superficiais",
    ])

    is_drug_administration = bool(plan.get("is_drug_administration")) or any(x in q for x in [
        "perfusão",
        "perfusao",
        "infusão",
        "infusao",
        "bomba de infusão",
        "bomba de infusao",
        "administra medicação",
        "administra medicacao",
        "administrar medicação",
        "administrar medicacao",
        "administra medicamento",
        "administrar medicamento",
    ])

    is_insulin_dose_software = bool(plan.get("is_insulin_dose_software")) or (
        ("software" in q or "app" in q or "algoritmo" in q)
        and any(x in q for x in ["insulina", "glicemia", "diabetes"])
        and any(x in q for x in ["dose", "dosagem", "calcula", "calcular", "recomenda", "recomendação", "recomendacao"])
    )

    is_software_diagnosis = (
        "software" in q
        and any(x in q for x in [
            "diagnóstico", "diagnostico", "radiografia", "radiografias",
            "pneumonia", "tac", "avc", "triagem", "prioriza", "priorização", "priorizacao",
        ])
    )

    is_ai_stroke_triage = (
        is_software_diagnosis
        and any(x in q for x in ["ia", "ai", "inteligência artificial", "inteligencia artificial"])
        and any(x in q for x in ["tac", "avc", "urgente", "radiologista", "prioriza", "priorização", "priorizacao"])
    )

    if is_urinary_catheter and rule5:
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: Classe I, se for um cateter urinário invasivo em relação a orifício corporal e de utilização temporária. {cite(rule5)}",
            "- Se a utilização prevista for a curto prazo, a classe provável passa para Classe IIa; se for a longo prazo, pode passar para Classe IIb, salvo exceções específicas.",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Duração de utilização prevista: temporária, curto prazo ou longo prazo.",
            "- Se é ligado a um dispositivo ativo.",
            "- Finalidade prevista e população/utilizadores.",
            *citations_block([art51, annex8, rule5]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    if is_orthopedic_implant and rule8:
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: Classe IIb, se for um implante ortopédico permanente sem medicamento incorporado e sem exceção que o faça subir de classe. {cite(rule8)}",
            "- Pode passar para Classe III se for, por exemplo, prótese articular total/parcial, implante em contacto com coração/sistema circulatório central/sistema nervoso central, dispositivo com efeito biológico, absorvível, destinado a administrar medicamentos, implante ativo, ou certos implantes de coluna/disco intervertebral.",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Tipo exato de implante ortopédico.",
            "- Se é prótese articular total/parcial ou componente auxiliar.",
            "- Local anatómico e contacto com estruturas críticas.",
            "- Existência de medicamento, efeito biológico, absorção ou transformação química.",
            *citations_block([art51, annex8, rule8]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    if is_cardiac_monitoring and rule10:
        classe = "Classe IIb" if is_high_acuity else "Classe IIa ou IIb"
        motivo = (
            "porque a pergunta indica monitorização/alerta de arritmias perigosas, ou seja, variações de parâmetro fisiológico vital que podem representar perigo imediato para o doente."
            if is_high_acuity
            else "porque a Regra 10 distingue dispositivos ativos de diagnóstico/monitorização e pode subir para IIb quando a natureza das variações monitorizadas puder resultar em perigo imediato para o doente."
        )
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: {classe}, {motivo} {cite(rule10)}",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Se o alerta é usado para decisão clínica urgente.",
            "- Se a arritmia detetada representa perigo imediato para o doente.",
            "- Se o dispositivo apenas regista dados ou se emite alertas/decisões clínicas.",
            *citations_block([art51, annex8, rule10]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    if is_wound_dressing and rule4:
        if is_superficial_wound_dressing:
            classe_line = (
                f"- Classe provável: Classe I, se a compressa/penso se destinar a feridas superficiais e atuar principalmente como barreira mecânica, compressão ou absorção de exsudados. {cite(rule4)}"
            )
        else:
            classe_line = (
                f"- Classe provável: depende da finalidade e do tipo de ferida. Pela Regra 4, pode ser Classe I, IIa ou IIb conforme o contacto com pele/membrana mucosa lesada e a função pretendida. {cite(rule4)}"
            )

        body = [
            "2. Classe MDR provável",
            classe_line,
            "- Se o produto se destinar principalmente a controlar o microambiente da pele ou membrana mucosa lesada, pode ser Classe IIa.",
            "- Se se destinar a feridas mais graves, por exemplo lesões cutâneas que tenham fissurado a derme e só possam cicatrizar por segunda intenção, pode ser Classe IIb.",
            "- A esterilidade não muda por si só a regra de classificação de base, mas pode implicar envolvimento de organismo notificado para os aspetos de esterilidade.",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Tipo de ferida: superficial, lesão com derme fissurada, membrana mucosa lesada ou ferida crónica.",
            "- Função principal: barreira/absorção, controlo de microambiente ou tratamento de ferida grave.",
            "- Se é fornecida estéril.",
            *citations_block([art51, annex8, rule4]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()


    if is_drug_administration and rule12:
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: Classe IIa, se for um dispositivo ativo destinado a administrar ou remover medicamentos, fluidos corporais ou outras substâncias. {cite(rule12)}",
            "- Pode passar para Classe IIb se a administração ou remoção for potencialmente perigosa, tendo em conta a natureza das substâncias, a parte do corpo envolvida ou o modo de aplicação.",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Medicamento/substância administrada.",
            "- Se a administração é automática, programável, contínua ou crítica.",
            "- Risco clínico de sobredosagem, subdosagem, atraso ou interrupção.",
            "- Contexto de utilização: hospitalar, domiciliário, emergência ou cuidados intensivos.",
            *citations_block([art51, annex8, rule12]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()
    
    
    if is_simple_thermometer and rule1:
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: Classe I, se for um termómetro simples não invasivo, sem componente ativa/digital/software/IA relevante para diagnóstico ou monitorização ativa. {cite(rule1)}",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Se é realmente simples/não invasivo.",
            "- Se não tem software, algoritmo, IA, infravermelhos ou função ativa de diagnóstico/monitorização.",
            "- Finalidade prevista pelo fabricante.",
            *citations_block([art51, annex8, rule1]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    if is_active_or_digital_thermometer and rule10:
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: Classe IIa, se o termómetro digital/ativo/infravermelhos se destinar a diagnóstico ou monitorização clínica da temperatura corporal. {cite(rule10)}",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "- A conclusão depende da finalidade prevista, do modo como a temperatura é usada e do impacto clínico da informação.",
            "",
            "3. Condições a confirmar",
            "- Se é usado para diagnóstico ou monitorização clínica.",
            "- Se tem software/algoritmo/IA autónomo que presta informação para decisões clínicas.",
            "- Se existem alertas ou decisões clínicas automatizadas.",
            *citations_block([art51, annex8, rule10]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    if is_ai_stroke_triage and rule11:
        body = [
            "2. Enquadramento MDR e AI Act",
            f"- O software pode qualificar-se como dispositivo médico se a finalidade prevista for apoiar diagnóstico, triagem ou priorização clínica. {cite(art2)}",
            f"- Classe MDR provável: Classe IIb se a priorização de TAC suspeita de AVC influenciar a urgência da revisão e um erro puder causar deterioração grave do estado de saúde; se for apenas apoio sem impacto clínico grave, o ponto de partida pode ser Classe IIa. {cite(rule11)}",
            f"- A classificação MDR deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            f"- Quanto ao AI Act, pode ser sistema de IA de risco elevado se cumprir o enquadramento do Artigo 6, nomeadamente se for sistema de IA usado como produto/componente abrangido por legislação harmonizada e sujeito a avaliação de conformidade por terceiros. {cite(ai6)}" if ai6 else "- Quanto ao AI Act, a categoria deve ser analisada separadamente; a classe MDR não é a mesma coisa que risco elevado no AI Act.",
            "",
            "3. Condições a confirmar",
            "- Se a priorização altera tempos de revisão ou decisão clínica.",
            "- Se o erro pode atrasar tratamento de AVC ou causar deterioração grave.",
            "- Se o software é parte de dispositivo médico ou software médico autónomo.",
            "- Se está sujeito a avaliação de conformidade por terceiro.",
            *citations_block([art2, art51, annex8, rule11, ai6]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()
    
    if is_insulin_dose_software and rule11:
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: Classe IIb, se o software calcula/recomenda dose de insulina usada numa decisão terapêutica e uma recomendação errada puder causar deterioração grave do estado de saúde. {cite(rule11)}",
            "- Pode ser Classe III se a decisão suportada puder causar morte ou deterioração irreversível do estado de saúde.",
            "- O ponto de partida da Regra 11 para software que presta informações usadas em decisões terapêuticas ou de diagnóstico é Classe IIa; no caso de dose de insulina, deve ser avaliada a subida para Classe IIb ou III conforme o impacto clínico previsível.",
            f"- A classificação deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Se o software apenas informa ou recomenda diretamente uma dose.",
            "- Se existe validação por profissional de saúde ou administração automática.",
            "- Consequências clínicas previsíveis de dose errada: hipoglicemia, hiperglicemia, hospitalização, coma ou morte.",
            "- População-alvo e contexto de utilização.",
            *citations_block([art51, annex8, rule11]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()
    
    
    if is_software_diagnosis and rule11:
        body = [
            "2. Classe MDR provável",
            f"- Classe provável: Classe IIa, porque o software presta informações utilizadas para decisões com fins de diagnóstico. {cite(rule11)}",
            "- Pode subir para Classe IIb ou Classe III se a decisão suportada puder causar deterioração grave, intervenção cirúrgica, morte ou deterioração irreversível; esses elementos têm de ser confirmados.",
            f"- A classificação MDR deve ser feita pelas regras do Anexo VIII. {cite(art51 or annex8)}",
            "",
            "3. Condições a confirmar",
            "- Finalidade prevista pelo fabricante.",
            "- Se o software apenas apoia ou se influencia diretamente a decisão clínica.",
            "- Gravidade do impacto clínico caso a informação esteja errada.",
            *citations_block([art51, annex8, rule11, ai6]),
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    return None


def build_canonical_device_qualification_answer(
    *,
    question: str,
    plan: Dict[str, Any],
    generation_indices: List[int],
    records: List[Dict[str, Any]],
) -> Optional[str]:
    if plan.get("intent") != "device_qualification":
        return None

    q = (question or "").lower()
    fixed = build_fixed_regulations_section(plan)

    def cite(c: Optional[str]) -> str:
        return f" [{c}]" if c else ""

    art2 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 2", "definições", "dispositivo médico", "dispositivo medico"],
    )
    recital19 = citation_for_matching_text(
        generation_indices,
        records,
        ["considerando (19)", "bem-estar", "estilo de vida", "software de uso geral"],
    )

    is_hydration_app = (
        ("hidratação" in q or "hidratacao" in q)
        and ("app" in q or "aplicação" in q or "aplicacao" in q)
        and ("sem finalidade médica" in q or "sem finalidade medica" in q or "apenas" in q)
    )

    is_smartwatch = "smartwatch" in q
    is_fitness_only = is_smartwatch and any(x in q for x in ["fitness", "passos", "sono", "bem-estar", "wellness"])
    is_afib_detection = is_smartwatch and any(x in q for x in [
        "fibrilhação", "fibrilhacao", "fibrilação", "fibrilacao", "arritmia", "arritmias"
    ])

    citations = [c for c in dict.fromkeys([art2, recital19]) if c]

    if is_hydration_app:
        body = [
            "2. Enquadramento MDR",
            f"- Em princípio, uma app que apenas recomenda hidratação geral e não tem finalidade médica prevista não é dispositivo médico MDR. {cite(recital19 or art2)}",
            "- Nesse cenário, não há obrigação de avaliação clínica ou PMCF/ACPC ao abrigo do MDR, porque essas obrigações pressupõem que o produto seja um dispositivo médico.",
            "- A conclusão muda se o fabricante fizer claims médicos, por exemplo diagnóstico, prevenção, monitorização ou tratamento de doença/desidratação.",
            "",
            "3. Condições a confirmar",
            "- Claims comerciais e instruções de utilização.",
            "- Se a app se destina apenas a bem-estar ou a uma finalidade médica específica.",
            "- Se recomenda hidratação geral ou se gere/monitoriza uma condição clínica.",
            "",
            "4. Citações usadas",
            *[f"- {c}" for c in citations],
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    if is_afib_detection:
        body = [
            "2. Enquadramento MDR",
            f"- Sim, muda o enquadramento: se o smartwatch for anunciado para deteção de fibrilhação auricular/arritmias, deixa de ser apenas fitness/bem-estar e passa a ter finalidade médica específica, como diagnóstico ou monitorização. {cite(art2)}",
            "- A classe MDR concreta deve depois ser avaliada pelas regras de classificação aplicáveis, em especial dispositivos ativos de diagnóstico/monitorização ou software, conforme a arquitetura do produto.",
            "",
            "3. Condições a confirmar",
            "- Se a funcionalidade é apenas informativa ou se apoia decisão clínica.",
            "- Se há alerta para o utilizador/profissional de saúde.",
            "- Se o algoritmo/software presta informação usada para diagnóstico.",
            "- Finalidade prevista e claims comerciais do fabricante.",
            "",
            "4. Citações usadas",
            *[f"- {c}" for c in citations],
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    if is_fitness_only:
        body = [
            "2. Enquadramento MDR",
            f"- Em princípio, não é dispositivo médico se o smartwatch for anunciado apenas para fitness, passos, sono, frequência cardíaca geral ou bem-estar, sem finalidade médica específica. {cite(recital19 or art2)}",
            "- O enquadramento muda se o fabricante fizer claims médicos, por exemplo diagnóstico, monitorização de doença, deteção de arritmias ou apoio a decisão clínica.",
            "",
            "3. Citações usadas",
            *[f"- {c}" for c in citations],
        ]
        return f"{fixed}\n\n" + "\n".join(body).strip()

    return None



def build_canonical_classification_and_scope_answer(
    *,
    question: str,
    plan: Dict[str, Any],
    generation_indices: List[int],
    records: List[Dict[str, Any]],
) -> Optional[str]:
    q = (question or "").lower()

    if plan.get("intent") != "classification_and_scope":
        return None

    def cite(c: Optional[str]) -> str:
        return f" [{c}]" if c else ""

    art2 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 2", "definições", "dispositivo médico", "dispositivo medico"],
    )
    art51 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 51", "classificação dos dispositivos", "classificacao dos dispositivos"],
    )
    annex8 = citation_for_matching_text(
        generation_indices,
        records,
        ["anexo viii", "regras de classificação", "regras de classificacao"],
    )
    rule10 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 10", "regra n.º 10", "regra 10", "processos fisiológicos vitais", "diagnóstico direto", "monitorização"],
    )
    rule11 = citation_for_matching_text(
        generation_indices,
        records,
        ["regra n.o 11", "regra n.º 11", "regra 11", "software destinado a prestar informações"],
    )
    ai6 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 6", "risco elevado", "alto risco"],
    )

    fixed = build_fixed_regulations_section(plan)

    is_thermometer = any(x in q for x in ["termómetro", "termometro", "temperatura"])
    is_active_or_digital_thermometer = is_thermometer and any(x in q for x in [
        "digital", "eletrónico", "eletronico", "electrónico", "electronico",
        "ativo", "ativa", "infravermelhos", "infra-vermelhos",
        "sensor", "algoritmo", "software", "ia", "inteligência artificial",
        "inteligencia artificial", "machine learning",
    ])

    is_ai_triage_software = (
        ("software" in q or "ia" in q or "ai" in q)
        and any(x in q for x in [
            "tac", "avc", "radiologista", "radiologistas",
            "prioriza", "priorizar", "triagem", "urgente",
        ])
    )

    if is_active_or_digital_thermometer:
        citations_used = [c for c in [art2, art51, annex8, rule10, ai6] if c]

        body = [
            "2. Qualificação como dispositivo médico",
            f"- Pode enquadrar-se como dispositivo médico se a finalidade prevista for diagnóstico ou monitorização clínica da temperatura corporal.{cite(art2)}",
            "- Se a finalidade for apenas bem-estar, uso geral ou informação não médica, a qualificação pode mudar.",
            "",
            "3. Classe MDR provável",
            f"- Classe provável: Classe IIa, se o termómetro digital/ativo/infravermelhos se destinar a diagnóstico ou monitorização clínica.{cite(rule10 or annex8)}",
            f"- A classificação MDR deve ser feita pelas regras do Anexo VIII.{cite(art51 or annex8)}",
            "- A classe pode mudar se o produto for apenas um termómetro simples não invasivo sem componente ativa/software/IA relevante, ou se a finalidade prevista não for médica.",
            "",
            "4. AI Act",
        ]

        if plan.get("mentions_ai"):
            if ai6:
                body.append(
                    f"- A componente de IA deve ser analisada separadamente no AI Act. Pode ser sistema de IA de risco elevado se preencher as condições do Artigo 6.{cite(ai6)}"
                )
            else:
                body.append(
                    "- A componente de IA deve ser analisada separadamente no AI Act; isto não deve ser confundido com a classe MDR."
                )

        body.extend([
            "",
            "5. Condições a confirmar",
            "- Finalidade prevista pelo fabricante.",
            "- Se é usado para diagnóstico ou monitorização clínica.",
            "- Se o algoritmo/IA presta informação usada em decisão clínica.",
            "- Se existem alertas, recomendações ou decisões automatizadas.",
            "",
            "6. Citações usadas",
            *[f"- {c}" for c in dict.fromkeys(citations_used)],
        ])

        return f"{fixed}\n\n" + "\n".join(body).strip()

    if not is_ai_triage_software:
        return None

    citations_used = [c for c in [art2, art51, annex8, rule11, ai6] if c]

    body = [
        "2. Qualificação como dispositivo médico",
        f"- Pode enquadrar-se como dispositivo médico se a finalidade prevista for apoiar diagnóstico, triagem ou monitorização clínica.{cite(art2)}",
        "",
        "3. Classe MDR provável",
        f"- Classe provável: Classe IIa, porque o software presta informações utilizadas para decisões com fins de diagnóstico ou terapêuticos.{cite(rule11 or annex8)}",
        "- Pode subir para Classe IIb ou Classe III se a decisão suportada puder causar deterioração grave, intervenção cirúrgica, morte ou deterioração irreversível; isto depende da finalidade prevista e do impacto clínico.",
        f"- A classificação MDR deve ser feita pelas regras do Anexo VIII.{cite(art51 or annex8)}",
        "",
        "4. AI Act",
    ]

    if ai6:
        body.append(
            f"- A componente de IA deve ser analisada separadamente no AI Act. Pode ser sistema de IA de risco elevado se preencher as condições do Artigo 6, nomeadamente por estar ligado a produto regulado/componente de segurança sujeito a avaliação da conformidade.{cite(ai6)}"
        )
    else:
        body.append(
            "- A componente de IA deve ser analisada separadamente no AI Act; isto não deve ser confundido com a classe MDR."
        )

    body.extend([
        "",
        "5. Condições a confirmar",
        "- Finalidade prevista exata: triagem, priorização, diagnóstico ou apoio à decisão.",
        "- Se o software apenas ordena exames ou se influencia diretamente a decisão clínica.",
        "- Gravidade do impacto se o software falhar ou atrasar a revisão.",
        "- Integração com fluxo clínico e responsabilidade do profissional de saúde.",
        "",
        "6. Citações usadas",
        *[f"- {c}" for c in dict.fromkeys(citations_used)],
    ])

    return f"{fixed}\n\n" + "\n".join(body).strip()



def build_canonical_ai_provider_obligations_answer(
    *,
    question: str,
    plan: Dict[str, Any],
    generation_indices: List[int],
    records: List[Dict[str, Any]],
) -> Optional[str]:
    if plan.get("intent") != "ai_provider_obligations":
        return None

    fixed = build_fixed_regulations_section(plan)

    art16 = citation_for_matching_text(
        generation_indices,
        records,
        ["artigo 16", "obrigações dos prestadores", "obrigacoes dos prestadores"],
    )

    if not art16:
        return None

    body = [
        "2. Obrigações principais do prestador de sistema de IA de risco elevado",
        f"1. Assegurar que o sistema de IA de risco elevado cumpre os requisitos aplicáveis. [{art16}]",
        f"2. Indicar no sistema, embalagem ou documentação o nome, nome comercial/marca registada e endereço de contacto do prestador, quando aplicável. [{art16}]",
        f"3. Dispor de um sistema de gestão da qualidade. [{art16}]",
        f"4. Conservar a documentação exigida. [{art16}]",
        f"5. Manter, quando esteja sob o seu controlo, os registos gerados automaticamente pelo sistema. [{art16}]",
        f"6. Assegurar que o sistema é sujeito ao procedimento de avaliação da conformidade aplicável. [{art16}]",
        f"7. Elaborar a declaração UE de conformidade. [{art16}]",
        f"8. Apor a marcação CE quando aplicável. [{art16}]",
        "",
        "3. Citações usadas",
        f"- {art16}",
    ]

    return f"{fixed}\n\n" + "\n".join(body).strip()



def _user_document_context_records(
    *,
    user_id: Optional[str],
    question: str,
    max_items: int = 4,
) -> tuple[List[Dict[str, Any]], List[float]]:
    if not user_id:
        return [], []

    if query_user_documents_for_rag is None:
        return [], []

    try:
        result = query_user_documents_for_rag(
            user_id=user_id,
            question=question,
            n_results=max_items,
        )
    except Exception:
        return [], []

    records = result.get("records") or []
    scores = result.get("scores") or []

    return records, scores


def _append_user_documents_to_context(
    *,
    records: List[Dict[str, Any]],
    adjusted_scores: List[float],
    generation_indices: List[int],
    selected_indices: List[int],
    user_doc_records: List[Dict[str, Any]],
    user_doc_scores: List[float],
) -> tuple[List[Dict[str, Any]], List[float], List[int], List[int]]:
    if not user_doc_records:
        return records, adjusted_scores, generation_indices, selected_indices

    combined_records = list(records)
    combined_scores = list(adjusted_scores)
    combined_generation_indices = list(generation_indices)
    combined_selected_indices = list(selected_indices)

    for record, score in zip(user_doc_records, user_doc_scores):
        idx = len(combined_records)
        combined_records.append(record)
        combined_scores.append(float(score))
        combined_generation_indices.append(idx)
        combined_selected_indices.append(idx)

    return (
        combined_records,
        combined_scores,
        combined_generation_indices,
        combined_selected_indices,
    )


def answer_question(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    user_id: Optional[str] = None,
    include_user_documents: bool = True,
) -> Dict[str, Any]:
    if not OLLAMA_CHAT_MODEL:
        raise ValueError("Falta OLLAMA_CHAT_MODEL no .env")

    question_clean = (question or "").strip()
    if not question_clean:
        raise ValueError("A pergunta não pode estar vazia.")

    is_follow_up = is_explicit_follow_up_question(question_clean)

    # O plano tem de ser SEMPRE calculado pela pergunta atual.
    # Nunca calcular o plano a partir da pergunta com histórico.
    plan = analyze_question(question_clean)

    retrieval_question = (
        build_contextual_question(question_clean, history)
        if is_follow_up and history
        else question_clean
    )

    if VECTOR_STORE == "chroma" and chroma_has_documents():
        n_results = 25 if plan.get("intent") in {
            "manufacturer_obligations",
            "classification_risk",
            "documentation",
            "document_generation",
            "ai_provider_obligations",
            "ai_high_risk",
            "gspr_requirements",
            "conformity_procedure",
            "device_qualification",
            "clinical_evaluation_terms",
            "classification_and_scope",
            "pms_plan",
            "pmcf",
            "ai_human_oversight",
            "ai_high_risk_requirements",
            "pmcf_plan",
            "pms_pmcf_vigilance",
        } else 12

        records, base_scores, adjusted_scores, _ = query_chroma_with_variants(
            retrieval_question,
            plan,
            n_results_per_query=n_results,
        )

        if not records:
            raise ValueError("Não foi possível recuperar contexto relevante.")

        retrieval_max_items = 18

        if plan.get("intent") == "classification_risk":
            retrieval_max_items = 10
        elif plan.get("intent") == "classification_and_scope":
            retrieval_max_items = 14

        selected_indices = select_chroma_retrieved_indices(
            records=records,
            adjusted_scores=adjusted_scores,
            plan=plan,
            max_items=retrieval_max_items,
        )
        retrieval_backend = "chroma"

    else:
        payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
        records = payload["records"]
        embeddings = payload["embeddings"]

        selected_indices, base_scores, adjusted_scores, _retrieval_plan = retrieve_relevant_indices(
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
    
    
    user_doc_records: List[Dict[str, Any]] = []
    user_doc_scores: List[float] = []

    if include_user_documents and user_id:
        user_doc_records, user_doc_scores = _user_document_context_records(
            user_id=user_id,
            question=retrieval_question,
            max_items=4,
        )
    
    canonical_classification_scope_answer = build_canonical_classification_and_scope_answer(
        question=question_clean,
        plan=plan,
        generation_indices=generation_indices,
        records=records,
    )

    if canonical_classification_scope_answer:
        return {
            "intent": plan["intent"],
            "target_docs": plan["target_docs"],
            "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
            "generation_sources": records_preview(
                cited_generation_indices(canonical_classification_scope_answer, generation_indices, records),
                records,
                adjusted_scores,
            ),
            "answer": canonical_classification_scope_answer,
            "retrieval_backend": retrieval_backend,
        }
    
    canonical_classification_answer = build_canonical_classification_answer(
        question=question_clean,
        plan=plan,
        generation_indices=generation_indices,
        records=records,
    )
    
    if canonical_classification_answer:
        return {
            "intent": plan["intent"],
            "target_docs": plan["target_docs"],
            "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
            "generation_sources": records_preview(
                cited_generation_indices(canonical_classification_answer, generation_indices, records),
                records,
                adjusted_scores,
            ),
            "answer": canonical_classification_answer,
            "retrieval_backend": retrieval_backend,
        }
        
    canonical_ai_provider_answer = build_canonical_ai_provider_obligations_answer(
        question=question_clean,
        plan=plan,
        generation_indices=generation_indices,
        records=records,
    )

    if canonical_ai_provider_answer:
        return {
            "intent": plan["intent"],
            "target_docs": plan["target_docs"],
            "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
            "generation_sources": records_preview(
                cited_generation_indices(canonical_ai_provider_answer, generation_indices, records),
                records,
                adjusted_scores,
            ),
            "answer": canonical_ai_provider_answer,
            "retrieval_backend": retrieval_backend,
        }
        
    canonical_device_answer = build_canonical_device_qualification_answer(
        question=question_clean,
        plan=plan,
        generation_indices=generation_indices,
        records=records,
    )

    if canonical_device_answer:
        return {
            "intent": plan["intent"],
            "target_docs": plan["target_docs"],
            "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
            "generation_sources": records_preview(generation_indices, records, adjusted_scores),
            "answer": canonical_device_answer,
            "retrieval_backend": retrieval_backend,
        }
        
    
    canonical_manufacturer_answer = build_canonical_manufacturer_obligations_answer(
        question=question_clean,
        plan=plan,
        generation_indices=generation_indices,
        records=records,
    )

    if canonical_manufacturer_answer:
        return {
            "intent": plan["intent"],
            "target_docs": plan["target_docs"],
            "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
            "generation_sources": records_preview(
                cited_generation_indices(canonical_manufacturer_answer, generation_indices, records),
                records,
                adjusted_scores,
            ),
            "answer": canonical_manufacturer_answer,
            "retrieval_backend": retrieval_backend,
        }
        

    if not has_minimum_retrieval_confidence(selected_indices, adjusted_scores) and not user_doc_records:
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

    (
        combined_records,
        combined_adjusted_scores,
        combined_generation_indices,
        combined_selected_indices,
    ) = _append_user_documents_to_context(
        records=records,
        adjusted_scores=adjusted_scores,
        generation_indices=generation_indices,
        selected_indices=selected_indices,
        user_doc_records=user_doc_records,
        user_doc_scores=user_doc_scores,
    )

    context = build_context(combined_generation_indices, combined_records)
    system_prompt = get_system_prompt(plan["intent"])

    # Só passar histórico ao prompt se for follow-up explícita.
    # Isto evita o modelo responder sobre AI Act ou fabricante por causa de mensagens anteriores.
    prompt = build_user_prompt(
        question_clean,
        context,
        plan["intent"],
        plan,
        history=history if is_follow_up else None,
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

    generated_text = improve_answer_if_needed(
        question=question_clean,
        answer=generated_text,
        generation_indices=combined_generation_indices,
        records=combined_records,
        plan=plan,
    )

    final_answer = f"{fixed_regulations_section}\n\n{generated_text}".strip()

    return {
        "intent": plan["intent"],
        "target_docs": plan["target_docs"],
        "retrieved_sources": records_preview(
            combined_selected_indices,
            combined_records,
            combined_adjusted_scores,
        ),
        "generation_sources": records_preview(
            cited_generation_indices(
                final_answer,
                combined_generation_indices,
                combined_records,
            ),
            combined_records,
            combined_adjusted_scores,
        ),
        "answer": final_answer,
        "retrieval_backend": retrieval_backend,
    }