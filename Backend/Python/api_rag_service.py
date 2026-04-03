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
from typing import Any, Dict, List

import ollama
from dotenv import load_dotenv

from rag_router_utils import (
    validate_embeddings_payload,
    retrieve_relevant_indices,
    build_context,
)


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
""",
    "requirement_lookup": """
Objetivo da resposta:
- Dar uma resposta curta e direta.
- Depois explicar apenas o que as fontes sustentam.
""",
    "conformity_procedure": """
Objetivo da resposta:
- Explicar o procedimento de forma estruturada por passos.
""",
    "documentation": """
Objetivo da resposta:
- Organizar a resposta por tipos de documentação.
""",
    "classification_risk": """
Objetivo da resposta:
- Identificar primeiro a base normativa concreta (artigo, anexo, regra ou ponto).
- Só depois explicar o que essa base permite concluir.
- Não fechar uma classe de risco sem base suficiente.
""",
}


# ---------------------------------------------------------------------------
# Limite máximo de fontes a usar na geração, por intenção
# ---------------------------------------------------------------------------
# Nem sempre convém enviar demasiadas fontes ao modelo. Este controlo evita
# prompts desnecessariamente grandes e ajuda a manter foco.
GENERATION_MAX_ITEMS_BY_INTENT = {
    "regulatory_scope": 6,
    "requirement_lookup": 6,
    "conformity_procedure": 8,
    "documentation": 8,
    "classification_risk": 6,
}


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


def select_generation_indices(
    selected_indices: List[int],
    records: List[Dict[str, Any]],
    adjusted_scores,
    plan: Dict[str, Any],
) -> List[int]:
    """
    Seleciona o subconjunto de fontes que será enviado ao modelo para geração.

    Esta função recebe as fontes já recuperadas na fase de retrieval e aplica
    uma seleção adicional orientada para geração de resposta, tentando equilibrar:
    - relevância;
    - especificidade;
    - diversidade de fontes;
    - cobertura de artigos/anexos importantes para o tipo de pergunta.

    Estratégia geral:
    - ordenar fontes por especificidade e score;
    - deduplicar;
    - forçar algumas fontes-chave por intenção;
    - limitar o número final de fontes;
    - remover fontes conhecidas como menos adequadas em certos casos
      (por exemplo Anexo VI quando se queria Anexo VIII).

    Args:
        selected_indices:
            Índices das fontes recuperadas no retrieval.
        records:
            Todos os registos disponíveis.
        adjusted_scores:
            Scores ajustados atribuídos no ranking.
        plan:
            Plano de retrieval, contendo intenção e documentos-alvo.

    Returns:
        List[int]:
            Lista final de índices a usar na construção do contexto de geração.
    """
    if not selected_indices:
        return []

    intent = plan.get("intent", "requirement_lookup")
    target_docs = plan.get("target_docs", [])
    max_items = GENERATION_MAX_ITEMS_BY_INTENT.get(intent, 6)

    # Ordena primeiro por especificidade normativa e depois por score ajustado.
    ranked = sorted(
        selected_indices,
        key=lambda i: (specificity_rank(records[i]), adjusted_scores[i]),
        reverse=True,
    )

    chosen: List[int] = []
    used_keys = set()

    def add_idx(idx: int) -> bool:
        """
        Adiciona um índice à lista final se ainda não tiver sido usado.

        Args:
            idx:
                Índice da fonte a adicionar.

        Returns:
            bool:
                True se a fonte foi adicionada; False se já existia.
        """
        key = citation_key(records[idx])
        if key in used_keys:
            return False
        chosen.append(idx)
        used_keys.add(key)
        return True

    # -----------------------------------------------------------------------
    # Regras especiais para perguntas sobre enquadramento regulatório
    # -----------------------------------------------------------------------
    if intent == "regulatory_scope":
        if target_docs == ["MDR"]:
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 5" in normalized_source_text(r) or
                              "colocação no mercado" in normalized_source_text(r),
                ],
            )
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 10" in normalized_source_text(r) or
                              "obrigações gerais dos fabricantes" in normalized_source_text(r),
                ],
            )
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "anexo i" in normalized_source_text(r) or
                              "requisitos gerais de segurança e desempenho" in normalized_source_text(r),
                ],
            )
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "anexo ii" in normalized_source_text(r) or
                              "documentação técnica" in normalized_source_text(r),
                ],
            )

        elif target_docs == ["MDR", "AI_ACT"]:
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 5" in normalized_source_text(r) or
                              "colocação no mercado" in normalized_source_text(r),
                ],
            )
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 10" in normalized_source_text(r) or
                              "obrigações gerais dos fabricantes" in normalized_source_text(r),
                ],
            )
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "AI_ACT",
                    lambda r: "artigo 6" in normalized_source_text(r) or
                              "alto risco" in normalized_source_text(r),
                ],
            )
            try_add_best_match(
                chosen, used_keys, ranked, records,
                [
                    lambda r: r.get("short_name") == "AI_ACT",
                    lambda r: "artigo 16" in normalized_source_text(r) or
                              "obrigações dos prestadores" in normalized_source_text(r),
                ],
            )

    # -----------------------------------------------------------------------
    # Regras especiais para perguntas sobre classificação/risco
    # -----------------------------------------------------------------------
    elif intent == "classification_risk":
        try_add_best_match(
            chosen, used_keys, ranked, records,
            [
                lambda r: r.get("short_name") == "MDR",
                lambda r: "artigo 51" in normalized_source_text(r) or
                          "classificação dos dispositivos" in normalized_source_text(r),
            ],
        )
        try_add_best_match(
            chosen, used_keys, ranked, records,
            [
                lambda r: r.get("short_name") == "MDR",
                lambda r: "anexo viii" in normalized_source_text(r) or
                          "regras de classificação" in normalized_source_text(r),
            ],
        )
        try_add_best_match(
            chosen, used_keys, ranked, records,
            [
                lambda r: r.get("short_name") == "MDR",
                lambda r: "regra" in normalized_source_text(r),
            ],
        )

    # Completa a lista final até ao limite máximo.
    for idx in ranked:
        if len(chosen) >= max_items:
            break
        add_idx(idx)

    # Filtra uma ambiguidade concreta: evita "Anexo VI" quando se pretendia
    # frequentemente "Anexo VIII" no contexto de classificação.
    filtered = []
    for idx in chosen:
        r = records[idx]
        text = normalized_source_text(r)

        if "anexo vi" in text and "anexo viii" not in text:
            continue

        filtered.append(idx)

    return filtered[:max_items]


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


def build_user_prompt(
    user_question: str,
    context: str,
    intent: str,
    plan: Dict[str, Any],
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
""",
        "classification_risk": """
Instruções adicionais:
- Identifica primeiro a regra, ponto, anexo ou artigo realmente relevante.
- Só depois diz o que essa base permite concluir.
- Se houver mais do que uma regra potencialmente aplicável, diz isso.
- Se faltar finalidade, modo de utilização, invasividade, duração de contacto ou contexto clínico, diz isso.
""",
    }.get(intent, "")

    return f"""
Tipo de pergunta detetado:
{intent}

Documentos-alvo:
{target_docs_text}

Regulamentos principais já identificados externamente:
{regulations_block}

Pergunta do utilizador:
{user_question}

Contexto recuperado:
{context}

{intent_specific_instruction}

Regras finais:
- Responde apenas com base no contexto.
- Quando fizeres uma afirmação normativa, associa-a à citação correta.
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
    return best >= 0.36


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
            "score_adjusted": float(adjusted_scores[idx]),
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


def search_question(question: str) -> Dict[str, Any]:
    """
    Executa apenas a fase de pesquisa semântica.

    Este método:
    - valida se o modelo de embeddings está configurado;
    - carrega o ficheiro de embeddings locais;
    - corre o pipeline de retrieval;
    - devolve intenção, documentos-alvo e fontes recuperadas.

    Não executa geração de resposta via LLM.

    Args:
        question:
            Pergunta do utilizador em linguagem natural.

    Returns:
        Dict[str, Any]:
            Estrutura resumida com resultados da pesquisa.

    Raises:
        ValueError:
            Se faltar configuração essencial no `.env`.
        FileNotFoundError:
            Se o ficheiro de embeddings não existir.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
    records = payload["records"]
    embeddings = payload["embeddings"]

    selected_indices, base_scores, adjusted_scores, plan = retrieve_relevant_indices(
        question=question,
        records=records,
        embeddings=embeddings,
        embed_model=OLLAMA_EMBED_MODEL,
    )

    return {
        "intent": plan["intent"],
        "target_docs": plan["target_docs"],
        "results": records_preview(selected_indices, records, adjusted_scores),
    }


def answer_question(question: str) -> Dict[str, Any]:
    """
    Executa o fluxo completo de retrieval + geração de resposta.

    Pipeline:
    1. valida configuração necessária;
    2. carrega embeddings locais;
    3. corre retrieval para identificar fontes relevantes;
    4. seleciona fontes para geração;
    5. decide entre:
       - fallback conservador, se a confiança for baixa;
       - geração normal via Ollama, se a confiança for suficiente;
    6. devolve a resposta final e os metadados úteis para a API.

    Args:
        question:
            Pergunta do utilizador.

    Returns:
        Dict[str, Any]:
            Estrutura completa com intenção, documentos-alvo, fontes recuperadas,
            fontes de geração e resposta final.

    Raises:
        ValueError:
            Se faltar configuração essencial ou se não for possível recuperar/
            selecionar contexto suficiente.
        FileNotFoundError:
            Se o ficheiro de embeddings não estiver disponível.
    """
    if not OLLAMA_EMBED_MODEL:
        raise ValueError("Falta OLLAMA_EMBED_MODEL no .env")

    if not OLLAMA_CHAT_MODEL:
        raise ValueError("Falta OLLAMA_CHAT_MODEL no .env")

    payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
    records = payload["records"]
    embeddings = payload["embeddings"]

    selected_indices, base_scores, adjusted_scores, plan = retrieve_relevant_indices(
        question=question,
        records=records,
        embeddings=embeddings,
        embed_model=OLLAMA_EMBED_MODEL,
    )

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

    # Se a recuperação não tiver confiança mínima, devolve uma resposta mais
    # prudente em vez de arriscar uma geração fraca.
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
        }

    # Constrói o contexto final a partir das fontes escolhidas e gera a resposta.
    context = build_context(generation_indices, records)
    system_prompt = get_system_prompt(plan["intent"])
    prompt = build_user_prompt(question, context, plan["intent"], plan)

    response = ollama.chat(
        model=OLLAMA_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )

    # Gera sempre a secção 1 fora do modelo, para garantir consistência.
    fixed_regulations_section = build_fixed_regulations_section(plan)
    generated_text = sanitize_generated_answer(response["message"]["content"])
    final_answer = f"{fixed_regulations_section}\n\n{generated_text}".strip()

    return {
        "intent": plan["intent"],
        "target_docs": plan["target_docs"],
        "retrieved_sources": records_preview(selected_indices, records, adjusted_scores),
        "generation_sources": records_preview(generation_indices, records, adjusted_scores),
        "answer": final_answer,
    }