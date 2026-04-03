"""
Script local de chat RAG sem ChromaDB para o projeto BridgeMedAI.

Este ficheiro executa um fluxo completo de pergunta-resposta usando:
- embeddings locais armazenados em ficheiro (`local_embeddings.pkl`);
- utilitários de retrieval definidos em `rag_router_utils.py`;
- geração de resposta com um modelo local via Ollama.

Diferença face ao `chat_rag_local.py`:
- este script não usa ChromaDB;
- a pesquisa é feita diretamente sobre a matriz local de embeddings;
- a lógica de retrieval e ranking é mais controlada e mais próxima da usada
  pelo backend principal.

Objetivos principais:
- testar localmente o pipeline completo sem depender de uma vector DB;
- validar o comportamento do ranking heurístico;
- inspecionar as fontes recuperadas e as fontes efetivamente usadas na geração;
- comparar resultados com a versão baseada em Chroma.

Fluxo resumido:
1. carregar variáveis do `.env`;
2. receber a pergunta pela linha de comandos;
3. validar a configuração mínima;
4. carregar o payload local de embeddings;
5. recuperar fontes relevantes com `retrieve_relevant_indices`;
6. selecionar o subconjunto de fontes para geração;
7. construir o contexto final;
8. gerar a resposta com Ollama;
9. imprimir a resposta no terminal.
"""

import os
import re
import sys
from pathlib import Path

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
# Mapeamento de nomes internos de regulamentos
# ---------------------------------------------------------------------------
# Este dicionário permite apresentar os nomes dos regulamentos de forma estável
# e legível na resposta final.
REGULATION_LABELS = {
    "MDR": "Regulamento (UE) 2017/745 (MDR)",
    "AI_ACT": "Regulamento (UE) 2024/1689 (AI Act)",
}


# ---------------------------------------------------------------------------
# Prompt base do sistema
# ---------------------------------------------------------------------------
# Define regras gerais que devem sempre ser respeitadas pelo modelo.
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
- Se o contexto não for suficiente para responder com confiança, diz claramente isso.
- Responde em português de Portugal.
- Nunca alteres os nomes nem os números oficiais dos regulamentos principais fornecidos no prompt.
- Nunca cries novos regulamentos, novos números de regulamento, nem placeholders como XXX ou YYY.
"""


# ---------------------------------------------------------------------------
# Instruções específicas por intenção
# ---------------------------------------------------------------------------
# O comportamento esperado da resposta varia conforme o tipo de pergunta.
SYSTEM_PROMPT_BY_INTENT = {
    "regulatory_scope": """
Objetivo da resposta:
- A secção 1 ("Regulamentos principais aplicáveis") já é fornecida externamente e não deves reescrevê-la.
- Nunca cries uma nova secção 1.
- Nunca inventes nomes ou números de regulamentos.
- Tu deves responder apenas às secções seguintes:
  2. Porque se aplicam
  3. Pontos principais a ter em conta já no início
  4. Limitações / informação adicional necessária
  5. Citações usadas
- Os artigos e anexos servem apenas para justificar a resposta, e não devem ser apresentados como regulamentos principais.
- Se a aplicação depender de informação adicional (por exemplo, classificação, finalidade exata, contexto clínico, ou se a IA for realmente parte do produto regulado), diz isso explicitamente.
""",
    "requirement_lookup": """
Objetivo da resposta:
- Explicar diretamente o que o contexto diz sobre o tema perguntado.
- Responder de forma objetiva, sem abrir demasiado o âmbito.
""",
    "conformity_procedure": """
Objetivo da resposta:
- Explicar o procedimento de conformidade aplicável com base no contexto.
""",
    "documentation": """
Objetivo da resposta:
- Identificar a documentação principal relevante para a pergunta.
""",
    "classification_risk": """
Objetivo da resposta:
- Explicar o enquadramento de classificação/risco com base no contexto.
- Não fechar uma classificação se o contexto não for suficiente.
""",
}


# ---------------------------------------------------------------------------
# Limite máximo de fontes por intenção
# ---------------------------------------------------------------------------
# Cada tipo de pergunta admite um número máximo de fontes a incluir no prompt.
GENERATION_MAX_ITEMS_BY_INTENT = {
    "regulatory_scope": 6,
    "requirement_lookup": 6,
    "conformity_procedure": 8,
    "documentation": 8,
    "classification_risk": 8,
}


def get_system_prompt(intent: str) -> str:
    """
    Constrói o prompt de sistema final em função da intenção detetada.

    Junta:
    - as regras base;
    - as instruções específicas do tipo de pergunta.

    Args:
        intent:
            Intenção inferida da pergunta.

    Returns:
        str:
            Prompt de sistema completo.
    """
    extra = SYSTEM_PROMPT_BY_INTENT.get(intent, SYSTEM_PROMPT_BY_INTENT["requirement_lookup"])
    return f"{SYSTEM_PROMPT_BASE.strip()}\n\n{extra.strip()}"


def citation_key(record):
    """
    Gera uma chave de deduplicação para uma fonte.

    Prioridade:
    1. citation_label
    2. chunk_id
    3. fallback por identidade do objeto

    Args:
        record:
            Registo de uma fonte normativa.

    Returns:
        str:
            Chave textual estável para deduplicação.
    """
    citation = (record.get("citation_label") or "").strip()
    if citation:
        return f"citation::{citation}"

    chunk_id = record.get("chunk_id")
    if chunk_id is not None:
        return f"chunk::{chunk_id}"

    return f"fallback::{id(record)}"


def normalized_source_text(record):
    """
    Constrói uma versão textual simplificada de uma fonte para matching heurístico.

    Usa:
    - citação;
    - número de secção;
    - título da secção.

    Args:
        record:
            Fonte normativa.

    Returns:
        str:
            Texto em minúsculas.
    """
    text = " ".join([
        str(record.get("citation_label", "")),
        str(record.get("section_number", "")),
        str(record.get("section_title", "")),
    ])
    return text.lower()


def try_add_best_match(chosen, used_keys, ranked, records, adjusted_scores, conditions):
    """
    Tenta adicionar a primeira fonte relevante ainda não escolhida que cumpra um conjunto de condições.

    Esta função é usada para forçar a inclusão de certas fontes-chave no prompt,
    por exemplo:
    - Artigo 10 MDR;
    - Anexo I MDR;
    - Artigo 6 AI Act.

    Args:
        chosen:
            Lista de índices já escolhidos.
        used_keys:
            Conjunto de chaves já usadas para deduplicação.
        ranked:
            Lista de índices ordenados por score.
        records:
            Lista completa de registos.
        adjusted_scores:
            Scores ajustados das fontes.
        conditions:
            Lista de funções booleanas a aplicar a cada registo.

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


def select_generation_indices(selected_indices, records, adjusted_scores, plan):
    """
    Seleciona o subconjunto de fontes que será usado na geração da resposta.

    Este passo é mais restritivo do que a recuperação inicial.
    O objetivo é construir um contexto:
    - compacto;
    - focado;
    - normativamente mais útil;
    - sem excesso de redundância.

    Para certos intents, tenta garantir fontes nucleares específicas.

    Args:
        selected_indices:
            Índices recuperados na fase de retrieval.
        records:
            Lista de registos normativos.
        adjusted_scores:
            Scores ajustados.
        plan:
            Plano inferido da pergunta.

    Returns:
        list:
            Índices das fontes a usar na geração.
    """
    if not selected_indices:
        return []

    intent = plan.get("intent", "requirement_lookup")
    target_docs = plan.get("target_docs", [])
    max_items = GENERATION_MAX_ITEMS_BY_INTENT.get(intent, 6)

    ranked = sorted(selected_indices, key=lambda i: adjusted_scores[i], reverse=True)

    chosen = []
    used_keys = set()

    def add_idx(idx):
        """
        Adiciona um índice à seleção final, evitando duplicados.

        Args:
            idx:
                Índice da fonte.

        Returns:
            bool:
                True se foi adicionada; False caso contrário.
        """
        key = citation_key(records[idx])
        if key in used_keys:
            return False
        chosen.append(idx)
        used_keys.add(key)
        return True

    # -----------------------------------------------------------------------
    # Seleção especializada para perguntas de enquadramento regulatório
    # -----------------------------------------------------------------------
    if intent == "regulatory_scope":
        if target_docs == ["MDR"]:
            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 5" in normalized_source_text(r) or "colocação no mercado" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 10" in normalized_source_text(r) or "obrigações gerais dos fabricantes" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "anexo i" in normalized_source_text(r) or "requisitos gerais de segurança e desempenho" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "anexo ii" in normalized_source_text(r) or "documentação técnica" in normalized_source_text(r)
                ]
            )

        elif target_docs == ["MDR", "AI_ACT"]:
            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 5" in normalized_source_text(r) or "colocação no mercado" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "artigo 10" in normalized_source_text(r) or "obrigações gerais dos fabricantes" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "MDR",
                    lambda r: "anexo i" in normalized_source_text(r) or "requisitos gerais de segurança e desempenho" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "AI_ACT",
                    lambda r: "artigo 6" in normalized_source_text(r) or "alto risco" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "AI_ACT",
                    lambda r: "artigo 16" in normalized_source_text(r) or "obrigações dos prestadores" in normalized_source_text(r)
                ]
            )

            try_add_best_match(
                chosen, used_keys, ranked, records, adjusted_scores,
                [
                    lambda r: r.get("short_name") == "AI_ACT",
                    lambda r: "artigo 25" in normalized_source_text(r) or "obrigações dos fabricantes de produtos" in normalized_source_text(r)
                ]
            )

        for idx in ranked:
            if len(chosen) >= max_items:
                break
            add_idx(idx)

        return chosen[:max_items]

    # -----------------------------------------------------------------------
    # Seleção genérica para outros intents
    # -----------------------------------------------------------------------
    for idx in ranked:
        if len(chosen) >= max_items:
            break
        add_idx(idx)

    return chosen


def print_retrieved_sources(selected_indices, records, adjusted_scores):
    """
    Imprime no terminal as fontes recuperadas no retrieval.

    Útil para debugging e inspeção manual do pipeline.

    Args:
        selected_indices:
            Índices das fontes recuperadas.
        records:
            Lista de registos.
        adjusted_scores:
            Scores ajustados.

    Returns:
        None
    """
    print("\nFontes recuperadas relevantes:\n")
    for idx in selected_indices:
        r = records[idx]
        print(
            f"- {r.get('citation_label', 'SEM_CITACAO')} "
            f"[{r.get('section_type', '')}] "
            f"(score ajustado: {adjusted_scores[idx]:.4f})"
        )


def print_generation_sources(generation_indices, records, adjusted_scores):
    """
    Imprime no terminal as fontes efetivamente usadas na geração da resposta.

    Isto permite comparar:
    - o conjunto inicialmente recuperado;
    - o subconjunto final passado ao modelo.

    Args:
        generation_indices:
            Índices das fontes de geração.
        records:
            Lista de registos.
        adjusted_scores:
            Scores ajustados.

    Returns:
        None
    """
    print("\nFontes usadas para gerar a resposta:\n")
    for idx in generation_indices:
        r = records[idx]
        print(
            f"- {r.get('citation_label', 'SEM_CITACAO')} "
            f"[{r.get('section_type', '')}] "
            f"(score ajustado: {adjusted_scores[idx]:.4f})"
        )


def build_regulations_block(target_docs):
    """
    Constrói o bloco textual com os regulamentos principais identificados.

    Args:
        target_docs:
            Lista de nomes curtos dos documentos-alvo.

    Returns:
        str:
            Lista formatada dos regulamentos principais.
    """
    regulation_lines = []

    for doc in target_docs:
        if doc in REGULATION_LABELS:
            regulation_lines.append(f"- {REGULATION_LABELS[doc]}")

    if not regulation_lines:
        return "- Sem enquadramento principal pré-identificado"

    return "\n".join(regulation_lines)


def build_fixed_regulations_section(plan: dict) -> str:
    """
    Constrói a secção fixa inicial da resposta.

    Esta secção é produzida fora do modelo para garantir:
    - consistência;
    - nomes corretos dos regulamentos;
    - ausência de alucinações sobre regulamentos principais.

    Args:
        plan:
            Plano inferido da pergunta.

    Returns:
        str:
            Secção textual '1. Regulamentos principais aplicáveis'.
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


def build_user_prompt(user_question: str, context: str, intent: str, plan: dict) -> str:
    """
    Constrói o prompt de utilizador final enviado ao modelo.

    O prompt inclui:
    - tipo de pergunta;
    - documentos-alvo;
    - regulamentos principais já identificados;
    - pergunta original;
    - contexto recuperado;
    - instruções finais de resposta.

    Args:
        user_question:
            Pergunta do utilizador.
        context:
            Contexto textual consolidado.
        intent:
            Intenção inferida.
        plan:
            Plano inferido do retrieval.

    Returns:
        str:
            Prompt final para o modelo de chat.
    """
    target_docs = plan.get("target_docs", [])
    target_docs_text = ", ".join(target_docs) if target_docs else "sem documento-alvo fixo"
    regulations_block = build_regulations_block(target_docs)

    intent_specific_instruction = {
        "regulatory_scope": """
Instruções adicionais para esta pergunta:
- A secção 1 já está determinada externamente e não deves reescrevê-la.
- Não cries uma nova secção 1.
- Começa diretamente na secção 2.
- Nunca inventes nomes ou números de regulamentos.
- Nunca uses placeholders como XXX ou YYY.
- Os regulamentos principais já identificados devem ser usados tal como estão.
- Não respondas com nomes de artigos como se fossem regulamentos principais.
- Se a resposta depender de elementos ainda não conhecidos (por exemplo, classificação exata, finalidade clínica específica ou enquadramento preciso da componente de IA), diz isso claramente.
""",
        "requirement_lookup": """
Instruções adicionais para esta pergunta:
- Responde de forma direta ao que foi perguntado.
- Resume o conteúdo normativo relevante sem alargar demasiado a resposta.
""",
        "conformity_procedure": """
Instruções adicionais para esta pergunta:
- Explica o procedimento de conformidade de forma estruturada.
- Dá prioridade a etapas, anexos, artigos e atores relevantes.
""",
        "documentation": """
Instruções adicionais para esta pergunta:
- Organiza a resposta por tipos de documentação.
- Explica para que serve cada documento principal.
""",
        "classification_risk": """
Instruções adicionais para esta pergunta:
- Explica apenas o que o contexto permite concluir sobre classificação/risco.
- Se faltar informação para fechar a classificação, diz isso de forma explícita.
""",
    }.get(intent, "")

    return f"""
Tipo de pergunta detetado:
{intent}

Documentos-alvo:
{target_docs_text}

Regulamentos principais já identificados externamente:
{regulations_block}

Nunca alteres estes nomes nem estes números.
Nunca apresentes artigos como se fossem regulamentos principais.

Pergunta do utilizador:
{user_question}

Contexto recuperado:
{context}

{intent_specific_instruction}

Regras finais:
- Responde apenas com base no contexto.
- Se existirem várias fontes, sintetiza sem misturar citações erradas.
- Quando mencionares uma obrigação, requisito, definição ou enquadramento, associa-o à citação correta.
- Não cries uma nova secção 1.
- Começa diretamente na secção 2.
- No fim, inclui apenas as citações realmente usadas na resposta.
"""


def sanitize_generated_answer(text: str) -> str:
    """
    Limpa a resposta gerada pelo modelo antes de a imprimir.

    Faz:
    - remoção de secções 1 repetidas;
    - remoção de placeholders inválidos;
    - normalização de quebras de linha.

    Args:
        text:
            Texto bruto gerado pelo modelo.

    Returns:
        str:
            Texto limpo.
    """
    if not text:
        return ""

    cleaned = text.strip()

    match = re.search(r"(?m)^\s*2[\.\)]\s*", cleaned)
    if match:
        cleaned = cleaned[match.start():].strip()

    cleaned = re.sub(r"(?mi)^.*\bXXX\b.*$", "", cleaned)
    cleaned = re.sub(r"(?mi)^.*\bYYY\b.*$", "", cleaned)
    cleaned = re.sub(r"(?mi)^\s*1[\.\)]\s*regulamentos principais aplic[aá]veis.*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned


def main():
    """
    Executa o fluxo principal do script local de chat RAG sem Chroma.

    Etapas:
    1. validar argumentos da linha de comandos;
    2. validar configuração mínima;
    3. carregar embeddings locais;
    4. recuperar fontes relevantes;
    5. selecionar fontes para geração;
    6. imprimir fontes recuperadas e fontes usadas;
    7. construir o contexto final;
    8. gerar resposta com Ollama;
    9. imprimir a resposta final.

    Uso esperado:
        python .\\Python\\chat_rag_local_no_chroma.py "pergunta"

    Returns:
        None
    """
    if len(sys.argv) < 2:
        print('Uso: python .\\Python\\chat_rag_local_no_chroma.py "pergunta"')
        return

    if not OLLAMA_EMBED_MODEL:
        print("[ERRO] Falta OLLAMA_EMBED_MODEL no .env")
        return

    if not OLLAMA_CHAT_MODEL:
        print("[ERRO] Falta OLLAMA_CHAT_MODEL no .env")
        return

    user_question = sys.argv[1].strip()

    if not user_question:
        print("[ERRO] A pergunta não pode estar vazia.")
        return

    try:
        # -------------------------------------------------------------------
        # Carregar e validar o payload local de embeddings
        # -------------------------------------------------------------------
        payload = validate_embeddings_payload(str(EMBEDDINGS_PATH))
        records = payload["records"]
        embeddings = payload["embeddings"]

        # -------------------------------------------------------------------
        # Retrieval semântico com heurísticas regulatórias
        # -------------------------------------------------------------------
        selected_indices, base_scores, adjusted_scores, plan = retrieve_relevant_indices(
            question=user_question,
            records=records,
            embeddings=embeddings,
            embed_model=OLLAMA_EMBED_MODEL
        )

        if not selected_indices:
            print("[ERRO] Não foi possível recuperar contexto relevante.")
            return

        # -------------------------------------------------------------------
        # Seleção final das fontes para geração
        # -------------------------------------------------------------------
        generation_indices = select_generation_indices(
            selected_indices=selected_indices,
            records=records,
            adjusted_scores=adjusted_scores,
            plan=plan
        )

        if not generation_indices:
            print("[ERRO] Não foi possível selecionar fontes para gerar a resposta.")
            return

        print("Intent detetada:", plan["intent"])
        print("Documentos-alvo:", plan["target_docs"] if plan["target_docs"] else "sem filtro fixo")

        print_retrieved_sources(selected_indices, records, adjusted_scores)
        print_generation_sources(generation_indices, records, adjusted_scores)

        # -------------------------------------------------------------------
        # Construção do contexto e geração da resposta
        # -------------------------------------------------------------------
        context = build_context(generation_indices, records)
        system_prompt = get_system_prompt(plan["intent"])
        prompt = build_user_prompt(user_question, context, plan["intent"], plan)

        response = ollama.chat(
            model=OLLAMA_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            stream=False
        )

        # -------------------------------------------------------------------
        # Montagem final da resposta
        # -------------------------------------------------------------------
        fixed_regulations_section = build_fixed_regulations_section(plan)
        generated_text = sanitize_generated_answer(response["message"]["content"])

        print("\nResposta:\n")
        print(fixed_regulations_section)
        print()
        print(generated_text)

    except FileNotFoundError as e:
        print(f"[ERRO] {e}")
    except ValueError as e:
        print(f"[ERRO] {e}")
    except Exception as e:
        print(f"[ERRO] Falha no chat RAG local: {e}")


# ---------------------------------------------------------------------------
# Ponto de entrada do script
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()