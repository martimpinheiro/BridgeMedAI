"""
Utilitários centrais de routing, retrieval e construção de contexto do BridgeMedAI.

Este módulo concentra a lógica intermédia entre:
- os embeddings já calculados e armazenados localmente;
- a pergunta recebida do utilizador;
- a seleção final das fontes normativas mais relevantes.

Responsabilidades principais:
- normalizar e tokenizar texto;
- inferir o perfil da pergunta e do dispositivo mencionado;
- detetar a intenção regulatória da pergunta;
- definir documentos-alvo prioritários (por exemplo MDR e/ou AI Act);
- construir variantes de query para retrieval mais robusto;
- calcular similaridade vetorial;
- ajustar scores com heurísticas regulatórias;
- deduplicar e selecionar as melhores fontes;
- construir o contexto textual que será enviado ao modelo de chat.

Este ficheiro é usado por módulos como:
- `api_rag_service.py`
- `search_embeddings_local.py`
- `chat_rag_local_no_chroma.py`

Ou seja, funciona como o "coração" do pipeline de retrieval semântico baseado
em embeddings locais.
"""

import os
import re
import pickle
import unicodedata
from typing import List, Dict, Any, Tuple

import numpy as np
import ollama


# ---------------------------------------------------------------------------
# Constantes de configuração do retrieval
# ---------------------------------------------------------------------------
# Estas constantes controlam o comportamento do pipeline de recuperação:
# - quantos resultados iniciais considerar;
# - limiares mínimos de score;
# - comprimento máximo do texto enviado por fonte ao contexto final.
INITIAL_RETRIEVAL_K = 40
MIN_ABSOLUTE_SCORE = 0.30
RELATIVE_SCORE_RATIO = 0.80
DOC_COVERAGE_MIN_SCORE = 0.37
MAX_CONTEXT_CHARS_PER_SOURCE = 1400


# ---------------------------------------------------------------------------
# Vocabulário auxiliar
# ---------------------------------------------------------------------------
# Stopwords simples usadas para reduzir ruído lexical nas comparações.
STOPWORDS = {
    "a", "o", "os", "as", "de", "da", "do", "das", "dos", "e", "ou", "para", "por",
    "com", "sem", "no", "na", "nos", "nas", "um", "uma", "uns", "umas", "que",
    "como", "qual", "quais", "sobre", "ao", "aos", "à", "às", "ser", "são", "é",
    "vou", "fazer", "preciso", "cumprir", "tenho", "ter", "diz", "dizer", "meu",
    "minha", "build", "make", "need", "requirements", "alguma", "coisa", "pergunte"
}

# Termos que ajudam a perceber se a pergunta fala efetivamente de dispositivos médicos.
MEDICAL_DEVICE_TERMS = {
    "termometro", "termómetro", "pacemaker", "marca-passo", "marcapasso",
    "implante", "implantavel", "implantável", "sensor", "monitor", "software medico",
    "software médico", "saude", "saúde", "diagnostico", "diagnóstico", "clinico",
    "clínico", "dispositivo medico", "dispositivo médico"
}

# Termos associados a IA / machine learning.
AI_TERMS = {
    "ia",
    "ai",
    "inteligencia artificial",
    "inteligência artificial",
    "machine learning",
    "aprendizagem automatica",
    "aprendizagem automática",
    "rede neural",
    "algoritmo de ia",
    "modelo de ia",
    "sistema de ia",
}

# Termos indicativos de perguntas sobre classificação e risco.
CLASSIFICATION_TERMS = {
    "classe", "classificacao", "classificação", "risco", "alto risco",
    "classificar", "anexo viii", "anexo 8", "regra"
}

# Termos associados a documentação técnica e dossiês.
DOCUMENTATION_TERMS = {
    "documentacao", "documentação", "dossie", "dossiê", "documentacao tecnica",
    "documentação técnica", "anexo ii", "anexo 2", "ficheiro tecnico", "ficheiro técnico"
}

# Termos ligados a avaliação da conformidade.
CONFORMITY_TERMS = {
    "avaliacao da conformidade", "avaliação da conformidade", "organismo notificado",
    "exame ue de tipo", "anexo ix", "anexo x", "anexo xi", "procedimento de conformidade"
}

MANUFACTURER_OBLIGATION_TERMS = {
    "obrigacoes gerais dos fabricantes",
    "obrigações gerais dos fabricantes",
    "obrigacoes gerais de um fabricante",
    "obrigações gerais de um fabricante",
    "obrigacoes do fabricante",
    "obrigações do fabricante",
    "obrigacoes dos fabricantes",
    "obrigações dos fabricantes",
    "fabricante segundo o mdr",
    "fabricantes segundo o mdr",
    "fabricante tem segundo o mdr",
    "fabricante tem no mdr",
    "artigo 10",
}

DOCUMENT_GENERATION_TERMS = {
    "gera o documento",
    "gerar o documento",
    "cria o documento",
    "criar o documento",
    "faz o documento",
    "fazer o documento",
    "redige o documento",
    "redigir o documento",
    "elabora o documento",
    "elaborar o documento",
    "gera o pmcf",
    "gerar o pmcf",
    "faz o pmcf",
    "fazer o pmcf",
    "cria o pmcf",
    "criar o pmcf",
    "documento pmcf",
    "plano pmcf",
    "relatorio pmcf",
    "relatório pmcf",
    "documento pms",
    "plano pms",
    "template",
    "modelo de documento",
    "pcmf",  # tolerância a typo
    "PCMF",
}


def normalize_text(text: str) -> str:
    """
    Normaliza texto para comparação lexical simples.

    Esta função:
    - converte para minúsculas;
    - remove espaços redundantes;
    - remove acentos via normalização Unicode;
    - facilita matching aproximado entre termos equivalentes.

    Exemplo:
        "Classificação do Dispositivo Médico"
        -> "classificacao do dispositivo medico"

    Args:
        text:
            Texto de entrada.

    Returns:
        str:
            Texto normalizado.
    """
    text = text or ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize_keywords(text: str) -> List[str]:
    """
    Extrai tokens relevantes de um texto normalizado.

    O objetivo é produzir uma lista simples de palavras-chave para operações
    como:
    - overlap lexical;
    - comparação de títulos e citações;
    - heurísticas de scoring.

    Regras:
    - usa apenas tokens alfanuméricos;
    - ignora tokens muito curtos;
    - remove stopwords.

    Args:
        text:
            Texto a tokenizar.

    Returns:
        List[str]:
            Lista de tokens relevantes.
    """
    text = normalize_text(text)
    tokens = re.findall(r"[a-zA-Z0-9_]+", text)
    return [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]





def contains_any(text: str, patterns: List[str]) -> bool:
    """
    Verifica se algum padrão textual está contido num texto.

    É uma função auxiliar simples para tornar o código de inferência mais legível.

    Args:
        text:
            Texto onde procurar.
        patterns:
            Lista de fragmentos/padrões textuais.

    Returns:
        bool:
            True se pelo menos um padrão estiver presente.
    """
    return any(p in text for p in patterns)


def contains_term(text: str, term: str) -> bool:
    """
    Procura termos evitando falsos positivos.

    Exemplo:
    - 'ai' deve bater em 'AI'
    - mas não deve bater em 'sinais' ou 'vitais'
    """
    text = normalize_text(text)
    term = normalize_text(term)

    if not term:
        return False

    # Expressões com espaços: match direto da expressão normalizada
    if " " in term:
        return term in text

    # Termos curtos como "ai" e "ia" só como palavra isolada
    if len(term) <= 2:
        return re.search(
            rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",
            text,
        ) is not None

    # Termos normais: palavra completa
    return re.search(
        rf"\b{re.escape(term)}\b",
        text,
    ) is not None


def cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    Calcula a similaridade de cosseno entre um vetor de query e uma matriz de embeddings.

    A função:
    - normaliza o vetor de query;
    - normaliza cada embedding da matriz;
    - devolve um vetor de scores de similaridade.

    Isto constitui a base vetorial do retrieval semântico.

    Args:
        query_vec:
            Embedding da query.
        matrix:
            Matriz de embeddings candidatos, um por linha.

    Returns:
        np.ndarray:
            Vetor com score de similaridade por registo.
    """
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    matrix_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10)
    return matrix_norm @ query_norm


def validate_embeddings_payload(path: str) -> Dict[str, Any]:
    """
    Valida e carrega o ficheiro local de embeddings serializado em pickle.

    Espera uma estrutura do tipo:
        {
            "records": [...],
            "embeddings": np.ndarray(...)
        }

    Valida:
    - existência do ficheiro;
    - formato do payload;
    - coerência entre número de registos e número de embeddings.

    Args:
        path:
            Caminho absoluto para o ficheiro de embeddings.

    Returns:
        Dict[str, Any]:
            Payload validado.

    Raises:
        FileNotFoundError:
            Se o ficheiro não existir.
        ValueError:
            Se o conteúdo não tiver a estrutura esperada.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Ficheiro de embeddings não encontrado: {path}")

    with open(path, "rb") as f:
        payload = pickle.load(f)

    if not isinstance(payload, dict):
        raise ValueError("O ficheiro de embeddings não contém um dicionário válido.")

    if "records" not in payload or "embeddings" not in payload:
        raise ValueError("O ficheiro de embeddings tem de conter as chaves 'records' e 'embeddings'.")

    records = payload["records"]
    embeddings = payload["embeddings"]

    if not isinstance(records, list) or len(records) == 0:
        raise ValueError("O campo 'records' está vazio ou inválido.")

    if not isinstance(embeddings, np.ndarray) or embeddings.shape[0] == 0:
        raise ValueError("O campo 'embeddings' está vazio ou inválido.")

    if len(records) != embeddings.shape[0]:
        raise ValueError("O número de records não corresponde ao número de embeddings.")

    return payload


def detect_device_profile(question: str) -> Dict[str, Any]:
    """
    Infere um perfil simples do dispositivo ou produto referido na pergunta.

    Este perfil serve para orientar a seleção de documentos e heurísticas de retrieval.

    Sinais detetados:
    - se parece ser um dispositivo médico;
    - se menciona IA;
    - se é implantável;
    - se é um termómetro;
    - se parece ser software;
    - se é não invasivo.

    Nota:
    esta deteção é heurística e baseada em matching textual simples.
    Não substitui análise regulatória real.

    Args:
        question:
            Pergunta do utilizador.

    Returns:
        Dict[str, Any]:
            Dicionário com flags booleanas de perfil.
    """
    q = normalize_text(question)

    is_medical_device = any(contains_term(q, term) for term in MEDICAL_DEVICE_TERMS)
    mentions_ai = any(contains_term(q, term) for term in AI_TERMS)

    is_implantable = any(term in q for term in [
        "pacemaker", "marca-passo", "marcapasso", "implante", "implantavel", "implantável"
    ])

    is_thermometer = any(term in q for term in [
        "termometro", "termómetro", "temperatura corporal", "temperatura"
    ])

    is_software = any(term in q for term in [
        "software", "saas", "aplicacao", "aplicação", "app"
    ])

    is_non_invasive = any(term in q for term in [
        "nao invasivo", "não invasivo"
    ])

    return {
        "is_medical_device": is_medical_device,
        "mentions_ai": mentions_ai,
        "is_implantable": is_implantable,
        "is_thermometer": is_thermometer,
        "is_software": is_software,
        "is_non_invasive": is_non_invasive,
    }


def analyze_question(question: str) -> Dict[str, Any]:
    """
    Analisa a pergunta e produz um plano inicial de retrieval.

    Ordem de prioridade:
    1. geração de documentos;
    2. âmbito regulatório;
    3. documentação técnica / PMS / PMCF;
    4. avaliação da conformidade;
    5. classificação de risco;
    6. lookup geral.
    """
    q = normalize_text(question)
    profile = detect_device_profile(question)

    mentions_mdr = (
        "mdr" in q
        or "regulamento 2017/745" in q
        or "regulamento ue 2017/745" in q
        or "medical device regulation" in q
    )

    mentions_ai_act = (
        "ai act" in q
        or "ia act" in q
        or "regulamento 2024/1689" in q
        or "regulamento ue 2024/1689" in q
        or "artificial intelligence act" in q
    )

    asks_document_generation = contains_any(q, list(DOCUMENT_GENERATION_TERMS))

    asks_regulatory_scope = any(term in q for term in [
        "que regulamentos",
        "quais regulamentos",
        "que legislacoes",
        "que legislacao",
        "que legislacao aplicavel",
        "que legislação",
        "que legislação aplicável",
        "quais legislacoes",
        "quais legislações",
        "que normas",
        "legislacao aplicavel",
        "legislação aplicável",
        "que tenho de cumprir",
        "que preciso de cumprir",
        "o que tenho de cumprir",
        "regulamentos tenho de cumprir",
        "requisitos tenho de cumprir",
        "obrigações tenho",
        "obrigacoes tenho",
        "ambito regulatorio",
        "âmbito regulatório",
    ])

    asks_documentation = (
        contains_any(q, list(DOCUMENTATION_TERMS))
        or any(term in q for term in [
            "pmcf",
            "pcmf",
            "pms",
            "vigilancia pos-comercializacao",
            "vigilância pós-comercialização",
            "acompanhamento clinico pos-comercializacao",
            "acompanhamento clínico pós-comercialização",
            "avaliacao clinica",
            "avaliação clínica",
            "relatorio de avaliacao clinica",
            "relatório de avaliação clínica",
            "anexo xiv",
            "anexo 14",
        ])
    )

    asks_manufacturer_obligations = contains_any(q, list(MANUFACTURER_OBLIGATION_TERMS)) or (
    "fabricante" in q
    and ("obrigacao" in q or "obrigacoes" in q or "obrigação" in q or "obrigações" in q)
    )

    asks_conformity = contains_any(q, list(CONFORMITY_TERMS))

    asks_classification = contains_any(q, list(CLASSIFICATION_TERMS))

    if asks_document_generation:
        intent = "document_generation"
    elif asks_manufacturer_obligations:
        intent = "manufacturer_obligations"
    elif asks_regulatory_scope:
        intent = "regulatory_scope"
    elif asks_documentation:
        intent = "documentation"
    elif asks_conformity:
        intent = "conformity_procedure"
    elif asks_classification:
        intent = "classification_risk"
    else:
        intent = "requirement_lookup"

    target_docs = []

    is_ai_medical_software = (
        profile.get("mentions_ai")
        and (
            profile.get("is_medical_device")
            or profile.get("is_software")
            or "software medico" in q
            or "software médico" in q
            or "dispositivo medico" in q
            or "dispositivo médico" in q
        )
    )

    if mentions_mdr and not mentions_ai_act and not is_ai_medical_software:
        target_docs = ["MDR"]

    elif mentions_ai_act and not mentions_mdr and not is_ai_medical_software:
        target_docs = ["AI_ACT"]

    elif is_ai_medical_software:
        target_docs = ["MDR", "AI_ACT"]

    elif profile["is_medical_device"]:
        target_docs = ["MDR"]

    elif intent in {
        "manufacturer_obligations",
        "documentation",
        "document_generation",
        "conformity_procedure",
        "classification_risk",
    }:
        target_docs = ["MDR"]
        
    return {
        "intent": intent,
        "target_docs": target_docs,
        **profile,
    }


def build_query_variants(question: str, plan: Dict[str, Any]) -> List[str]:
    """
    Gera variantes de query para reforçar a recuperação semântica.
    """
    queries = [question.strip()]
    intent = plan["intent"]
    target_docs = plan["target_docs"]
    q_norm = normalize_text(question)

    if intent == "regulatory_scope":
        if target_docs == ["MDR", "AI_ACT"]:
            queries.append("MDR artigo 5 artigo 10 anexo i anexo ii dispositivo médico fabricante requisitos gerais segurança desempenho")
            queries.append("AI Act artigo 6 artigo 9 artigo 10 artigo 11 artigo 16 artigo 25 artigo 43 sistema de IA de risco elevado")
            queries.append("dispositivo médico com IA MDR AI Act obrigações fabricante prestador deployer alto risco")
        elif target_docs == ["MDR"]:
            queries.append("MDR artigo 5 artigo 10 anexo i anexo ii dispositivo médico fabricante requisitos gerais segurança desempenho documentação técnica")
        elif target_docs == ["AI_ACT"]:
            queries.append("AI Act artigo 6 artigo 9 artigo 10 artigo 11 artigo 16 artigo 25 alto risco sistema de IA")
        else:
            queries.append("MDR AI Act regulamentos aplicáveis dispositivo médico software inteligência artificial obrigações")

    
    elif intent == "manufacturer_obligations":
        queries.append("MDR Artigo 10 obrigações gerais dos fabricantes sistema de gestão da qualidade gestão de risco avaliação clínica documentação técnica")
        queries.append("MDR fabricante obrigações gerais conformidade dispositivo requisitos gerais segurança desempenho vigilância pós-comercialização")
        queries.append("MDR fabricante artigo 10 artigo 15 artigo 83 artigo 84 artigo 86 documentação técnica avaliação clínica")
        queries.append("MDR fabricante declaração UE de conformidade marcação CE UDI registo dispositivo")
    
    
    elif intent == "conformity_procedure":
        queries.append("MDR avaliação da conformidade artigo 52 anexo ix anexo x anexo xi organismo notificado marcação CE")
        queries.append("MDR procedimentos avaliação da conformidade classe I IIa IIb III fabricante organismo notificado")
        if plan.get("mentions_ai"):
            queries.append("AI Act artigo 43 avaliação da conformidade sistema de IA de alto risco")

    elif intent == "documentation":
        queries.append("MDR anexo II documentação técnica descrição especificação conceção fabrico requisitos gerais segurança desempenho")
        queries.append("MDR anexo III documentação técnica vigilância pós-comercialização plano PMS relatório PMS")
        queries.append("MDR artigo 10 obrigações gerais dos fabricantes documentação técnica sistema gestão risco")
        queries.append("MDR artigo 61 avaliação clínica anexo XIV relatório avaliação clínica PMCF")
        queries.append("MDR acompanhamento clínico pós-comercialização PMCF anexo XIV parte B plano PMCF")
        if plan.get("mentions_ai"):
            queries.append("AI Act documentação técnica artigo 11 artigo 16 artigo 18 sistema de IA")

    elif intent == "document_generation":
        if "pmcf" in q_norm or "pcmf" in q_norm:
            queries.append("MDR PMCF acompanhamento clínico pós-comercialização anexo XIV parte B plano PMCF avaliação clínica")
            queries.append("MDR artigo 61 avaliação clínica PMCF acompanhamento clínico pós-comercialização documentação técnica")
            queries.append("MDR anexo II documentação técnica anexo III vigilância pós-comercialização PMCF")
            queries.append("MDR plano PMCF objetivos métodos dados clínicos segurança desempenho pós-comercialização")
        elif "pms" in q_norm or "vigilancia pos-comercializacao" in q_norm:
            queries.append("MDR plano de vigilância pós-comercialização artigo 84 relatório PMS anexo III")
            queries.append("MDR anexo III documentação técnica vigilância pós-comercialização PMS")
        else:
            queries.append("MDR anexo II documentação técnica anexo III vigilância pós-comercialização artigo 10")
            queries.append("MDR artigo 61 avaliação clínica anexo XIV documentação técnica")

    elif intent == "classification_risk":
        queries.append("MDR artigo 51 anexo VIII regras de classificação classe risco dispositivo médico")
        queries.append("MDR anexo VIII regra 1 dispositivos não invasivos classe I")
        queries.append("MDR anexo VIII regra 10 dispositivos ativos diagnóstico monitorização processos fisiológicos vitais")
        queries.append("MDR anexo VIII regra 11 software diagnóstico terapêutico classe IIa IIb III")

        if plan.get("is_thermometer"):
            queries.append("MDR termómetro digital temperatura corporal dispositivo ativo medição diagnóstico monitorização regra 10 anexo VIII")
            queries.append("MDR dispositivo não invasivo medição temperatura corporal regra 1 regra 10 classificação anexo VIII")

        if plan.get("is_software"):
            queries.append("MDR software destinado a prestar informações decisões diagnóstico terapêutico regra 11 anexo VIII")

        if plan.get("mentions_ai"):
            queries.append("AI Act artigo 6 anexo III sistema de IA de alto risco dispositivo médico")

    else:
        queries.append(f"{question.strip()} requisitos aplicáveis obrigação definição")
        if plan.get("is_medical_device"):
            queries.append("MDR artigo 10 obrigações fabricante requisitos gerais segurança desempenho documentação técnica")
        if plan.get("mentions_ai"):
            queries.append("AI Act obrigações sistema de IA artigo 16 artigo 25 artigo 43")

    queries = [q for q in queries if q]
    return list(dict.fromkeys(queries))


def lexical_overlap_bonus(question: str, record: Dict[str, Any]) -> float:
    """
    Calcula um pequeno bónus com base no overlap lexical entre pergunta e fonte.

    Este bónus não substitui o embedding-based retrieval, mas ajuda a favorecer
    fontes cujo título, citação ou chunk partilham palavras importantes com a pergunta.

    O valor é limitado para não dominar a componente vetorial.

    Args:
        question:
            Pergunta do utilizador.
        record:
            Registo de fonte candidata.

    Returns:
        float:
            Bónus adicional de score.
    """
    q_tokens = set(tokenize_keywords(question))
    if not q_tokens:
        return 0.0

    searchable_text = " ".join([
        str(record.get("citation_label", "")),
        str(record.get("section_number", "")),
        str(record.get("section_title", "")),
        str(record.get("chunk_text", ""))[:700],
    ])

    r_tokens = set(tokenize_keywords(searchable_text))
    if not r_tokens:
        return 0.0

    overlap = q_tokens.intersection(r_tokens)
    ratio = len(overlap) / max(1, len(q_tokens))
    return min(0.16, ratio * 0.16)


def section_type_bonus(intent: str, section_type: str) -> float:
    """
    Atribui um bónus/penalização dependendo do tipo de secção e da intenção.

    Ideia:
    - para classificação, regras e pontos costumam ser mais importantes;
    - para documentação, anexos e artigos relevantes tendem a pesar mais;
    - preâmbulos/considerandos/documentos inteiros tendem a ser menos úteis.

    Args:
        intent:
            Intenção da pergunta.
        section_type:
            Tipo da secção da fonte.

    Returns:
        float:
            Ajuste aditivo ao score.
    """
    table = {
        "regulatory_scope": {
            "article": 0.08,
            "annex": 0.06,
            "chapter": 0.02,
            "recital": -0.08,
            "preamble": -0.10,
            "document": -0.12,
        },
        "conformity_procedure": {
            "annex": 0.12,
            "article": 0.08,
            "chapter": 0.02,
            "recital": -0.08,
            "preamble": -0.10,
            "document": -0.12,
        },
        "documentation": {
            "annex": 0.12,
            "article": 0.07,
            "chapter": 0.02,
            "recital": -0.08,
            "preamble": -0.10,
            "document": -0.12,
        },
        "classification_risk": {
            "rule": 0.18,
            "point": 0.12,
            "annex": 0.14,
            "article": 0.08,
            "chapter": -0.02,
            "recital": -0.08,
            "preamble": -0.10,
            "document": -0.12,
        },
        "requirement_lookup": {
            "article": 0.08,
            "annex": 0.07,
            "point": 0.06,
            "rule": 0.08,
            "chapter": 0.03,
            "recital": -0.04,
            "preamble": -0.06,
            "document": -0.10,
        },
        "document_generation": {
            "annex": 0.13,
            "article": 0.08,
            "point": 0.07,
            "rule": -0.04,
            "chapter": 0.01,
            "recital": -0.08,
            "preamble": -0.10,
            "document": -0.12,
        },
        "manufacturer_obligations": {
            "article": 0.12,
            "annex": 0.05,
            "point": 0.04,
            "chapter": -0.04,
            "recital": -0.08,
            "preamble": -0.10,
            "document": -0.12,
        },
    }
    return table.get(intent, {}).get(section_type, 0.0)


def doc_bonus(plan: Dict[str, Any], record: Dict[str, Any]) -> float:
    """
    Dá bónus a documentos-alvo e penaliza fontes fora do foco principal.

    Exemplo:
    - se a pergunta aponta para MDR, fontes MDR recebem bónus;
    - se a pergunta é claramente sobre MDR + AI Act, ambos podem ser favorecidos.

    Args:
        plan:
            Plano inferido da pergunta.
        record:
            Fonte candidata.

    Returns:
        float:
            Ajuste de score por adequação documental.
    """
    target_docs = plan["target_docs"]
    short_name = record.get("short_name", "")

    if target_docs:
        return 0.07 if short_name in target_docs else -0.05

    bonus = 0.0
    if plan["mentions_ai"] and short_name == "AI_ACT":
        bonus += 0.04
    if plan["is_medical_device"] and short_name == "MDR":
        bonus += 0.04
    return bonus


def granularity_bonus(record: Dict[str, Any]) -> float:
    """
    Favorece fontes mais granulares e específicas.

    Exemplos de granularidade útil:
    - regras;
    - pontos;
    - citações curtas e bem definidas.

    A ideia é privilegiar secções mais diretamente acionáveis em vez de blocos
    demasiado largos.

    Args:
        record:
            Fonte candidata.

    Returns:
        float:
            Ajuste de score por granularidade.
    """
    citation = normalize_text(str(record.get("citation_label", "")))
    title = normalize_text(str(record.get("section_title", "")))
    section_type = record.get("section_type", "")

    bonus = 0.0

    if "regra" in citation or "rule" in citation:
        bonus += 0.10
    if "ponto" in citation:
        bonus += 0.06
    if section_type == "rule":
        bonus += 0.08
    if section_type == "point":
        bonus += 0.05
    if len(title) > 0 and len(title) < 120:
        bonus += 0.02

    return bonus


def intent_pattern_bonus(plan: Dict[str, Any], record: Dict[str, Any]) -> float:
    """
    Aplica bónus heurísticos com base em padrões fortemente relevantes para a intenção.

    Esta é uma das heurísticas mais importantes do sistema.
    Em vez de tratar todas as fontes semanticamente próximas de forma igual,
    reforça explicitamente secções que costumam ser nucleares para cada tipo de pergunta.

    Exemplos:
    - regulatory_scope -> Artigo 10 MDR, Artigo 16 AI Act, Anexo I, etc.
    - classification_risk -> Artigo 51, Anexo VIII, regras de classificação.

    Args:
        plan:
            Plano inferido da pergunta.
        record:
            Fonte candidata.

    Returns:
        float:
            Bónus adicional por adequação específica ao intent.
    """
    intent = plan["intent"]
    short_name = record.get("short_name", "")
    text = normalize_text(
        f"{record.get('citation_label', '')} "
        f"{record.get('section_number', '')} "
        f"{record.get('section_title', '')} "
        f"{record.get('chunk_text', '')[:700]}"
    )

    bonus = 0.0
    
    if intent == "manufacturer_obligations":
        if short_name == "MDR":
            if contains_any(text, ["artigo 10", "obrigacoes gerais dos fabricantes", "obrigações gerais dos fabricantes"]):
                bonus += 0.45
            if contains_any(text, ["artigo 15", "pessoa responsavel pela observancia", "pessoa responsável pela observância"]):
                bonus += 0.16
            if contains_any(text, ["artigo 19", "declaracao ue de conformidade", "declaração ue de conformidade"]):
                bonus += 0.14
            if contains_any(text, ["artigo 20", "marcacao ce", "marcação ce"]):
                bonus += 0.14
            if contains_any(text, ["artigo 27", "udi", "identificacao unica do dispositivo", "identificação única do dispositivo"]):
                bonus += 0.12
            if contains_any(text, ["artigo 29", "registo dos dispositivos"]):
                bonus += 0.12
            if contains_any(text, ["artigo 31", "registo dos fabricantes"]):
                bonus += 0.12
            if contains_any(text, ["artigo 61", "avaliacao clinica", "avaliação clínica"]):
                bonus += 0.14
            if contains_any(text, ["artigo 83", "vigilancia pos-comercializacao", "vigilância pós-comercialização"]):
                bonus += 0.14
            if contains_any(text, ["artigo 84", "plano de vigilancia pos-comercializacao", "plano de vigilância pós-comercialização"]):
                bonus += 0.12
            if contains_any(text, ["artigo 86", "relatorio periodico de seguranca", "relatório periódico de segurança"]):
                bonus += 0.10
            if contains_any(text, ["anexo i", "requisitos gerais de seguranca e desempenho", "requisitos gerais de segurança e desempenho"]):
                bonus += 0.12
            if contains_any(text, ["anexo ii", "documentacao tecnica", "documentação técnica"]):
                bonus += 0.14
            if contains_any(text, ["anexo iii", "documentacao tecnica relativa a vigilancia", "documentação técnica relativa à vigilância"]):
                bonus += 0.12
    

    elif intent == "regulatory_scope":
        if short_name == "MDR":
            if contains_any(text, ["artigo 5", "colocacao no mercado", "entrada em servico"]):
                bonus += 0.18
            if contains_any(text, ["artigo 10", "obrigacoes gerais dos fabricantes"]):
                bonus += 0.22
            if contains_any(text, ["anexo i", "requisitos gerais de seguranca e desempenho"]):
                bonus += 0.16
            if contains_any(text, ["anexo ii", "documentacao tecnica"]):
                bonus += 0.10

        if short_name == "AI_ACT":
            if contains_any(text, ["artigo 6", "alto risco", "high-risk"]):
                bonus += 0.22
            if contains_any(text, ["artigo 9", "sistema de gestao de riscos"]):
                bonus += 0.16
            if contains_any(text, ["artigo 16", "obrigacoes dos prestadores"]):
                bonus += 0.18
            if contains_any(text, ["artigo 25", "obrigacoes dos fabricantes de produtos"]):
                bonus += 0.18
            if contains_any(text, ["artigo 43", "avaliacao da conformidade"]):
                bonus += 0.12

    elif intent == "conformity_procedure":
        if contains_any(text, [
            "avaliacao da conformidade", "organismo notificado", "anexo ix",
            "anexo x", "anexo xi", "exame ue de tipo"
        ]):
            bonus += 0.16

    elif intent == "documentation":
        if contains_any(text, [
            "documentacao tecnica", "anexo ii", "anexo iii", "avaliacao clinica",
            "vigilancia pos-comercializacao", "vigilância pós-comercialização"
        ]):
            bonus += 0.16

    elif intent == "document_generation":
        if short_name == "MDR":
            if contains_any(text, ["anexo ii", "documentacao tecnica", "documentação técnica"]):
                bonus += 0.18
            if contains_any(text, ["anexo iii", "vigilancia pos-comercializacao", "vigilância pós-comercialização"]):
                bonus += 0.18
            if contains_any(text, ["artigo 61", "avaliacao clinica", "avaliação clínica"]):
                bonus += 0.16
            if contains_any(text, ["anexo xiv", "pmcf", "acompanhamento clinico pos-comercializacao", "acompanhamento clínico pós-comercialização"]):
                bonus += 0.22
            if contains_any(text, ["artigo 10", "obrigacoes gerais dos fabricantes", "obrigações gerais dos fabricantes"]):
                bonus += 0.10
    
    
    elif intent == "classification_risk":
        if short_name == "MDR":
            if contains_any(text, ["artigo 51", "classificacao dos dispositivos", "classificação dos dispositivos"]):
                bonus += 0.18
            if contains_any(text, ["anexo viii", "regras de classificacao", "regras de classificação"]):
                bonus += 0.24
            if contains_any(text, ["regra 1", "regra 2", "regra 3", "regra 4", "regra 5", "regra"]):
                bonus += 0.22
            if contains_any(text, ["nao invasivo", "não invasivo", "temperatura corporal", "medicao", "medição"]):
                bonus += 0.20

        if plan["mentions_ai"] and short_name == "AI_ACT" and contains_any(text, ["artigo 6", "anexo iii", "alto risco"]):
            bonus += 0.18

    return bonus


def negative_pattern_penalty(plan: Dict[str, Any], record: Dict[str, Any]) -> float:
    """
    Penaliza fontes que costumam ser falsos positivos para certas intenções.

    Esta função reduz score de fontes semanticamente próximas mas normativamente
    menos adequadas à pergunta feita.

    Exemplos:
    - em regulatory_scope, certos artigos institucionais podem desviar a resposta;
    - em classification_risk, Anexo VI pode aparecer indevidamente em vez de Anexo VIII.

    Args:
        plan:
            Plano inferido da pergunta.
        record:
            Fonte candidata.

    Returns:
        float:
            Penalização aditiva ao score.
        """
    intent = plan["intent"]
    text = normalize_text(
        f"{record.get('citation_label', '')} "
        f"{record.get('section_number', '')} "
        f"{record.get('section_title', '')}"
    )

    penalty = 0.0
    
    if intent == "manufacturer_obligations":
        if contains_any(text, [
            "anexo vii",
            "organismos notificados",
            "organismo notificado",
            "requisitos a cumprir pelos organismos notificados",
            "artigo 55",
            "mecanismo de escrutinio",
            "mecanismo de escrutínio",
            "artigo 57",
            "sistema eletronico relativo aos organismos notificados",
            "sistema eletrónico relativo aos organismos notificados",
            "anexo xiii",
            "dispositivos feitos por medida",
            "procedimento aplicavel aos dispositivos feitos por medida",
            "procedimento aplicável aos dispositivos feitos por medida",
            "capitulo v",
            "capítulo v",

            # bloquear fontes institucionais
            "artigo 105",
            "atribuicoes do mdcg",
            "atribuições do mdcg",
            "mdcg",
            "artigo 106",
            "artigo 107",
            "comissao",
            "comissão",
            "autoridades competentes",
            "autoridade competente",
            "grupo de coordenacao dos dispositivos medicos",
            "grupo de coordenação dos dispositivos médicos",
        ]):
            penalty -= 0.90

        if record.get("section_type") == "chapter":
            penalty -= 0.20
    

    if intent == "regulatory_scope":
        if contains_any(text, [
            "artigo 105", "atribuicoes do mdcg", "artigo 86", "artigo 89",
            "resumo da seguranca e do desempenho clinico", "artigo 111", "artigo 80"
        ]):
            penalty -= 0.18

    if intent == "classification_risk":
        if contains_any(text, [
            "anexo iv",
            "declaração ue de conformidade",
            "declaracao ue de conformidade",
            "anexo ix",
            "anexo x",
            "anexo xi",
            "avaliação da conformidade",
            "avaliacao da conformidade",
            "organismo notificado",
        ]):
            penalty -= 0.45

        if record.get("section_type") == "chapter":
            penalty -= 0.25

    if record.get("section_type") in {"recital", "preamble", "document"}:
        penalty -= 0.02
        
    if intent in {"documentation", "document_generation"}:
        if contains_any(text, [
            "regras de classificacao",
            "regras de classificação",
            "regra 1",
            "regra 7",
            "regra 10",
            "regra 11",
            "regra 12",
            "regra 17",
            "regra 22",
        ]):
            penalty -= 0.28

    return penalty


def adjust_score(base_score: float, record: Dict[str, Any], plan: Dict[str, Any], question: str) -> float:
    """
    Calcula o score final ajustado de uma fonte.

    O score ajustado combina:
    - similaridade vetorial base;
    - bónus por tipo de secção;
    - bónus por documento-alvo;
    - bónus por granularidade;
    - overlap lexical;
    - bónus específicos por intenção;
    - penalizações de padrões negativos.

    Este score é a métrica principal usada na seleção das fontes.

    Args:
        base_score:
            Similaridade vetorial inicial.
        record:
            Fonte candidata.
        plan:
            Plano inferido da pergunta.
        question:
            Pergunta original.

    Returns:
        float:
            Score final ajustado.
    """
    score = base_score
    score += section_type_bonus(plan["intent"], record.get("section_type", ""))
    score += doc_bonus(plan, record)
    score += granularity_bonus(record)
    score += lexical_overlap_bonus(question, record)
    score += intent_pattern_bonus(plan, record)
    score += negative_pattern_penalty(plan, record)
    return score


def deduplicate_ranked_indices(ranked_indices: np.ndarray, records: List[Dict[str, Any]]) -> List[int]:
    """
    Remove duplicados da lista de índices ordenados.

    A deduplicação é importante porque o mesmo artigo ou secção pode existir
    em vários chunks semelhantes, e não interessa apresentar múltiplas entradas
    quase idênticas na seleção final.

    A prioridade de chave é:
    - citation_label;
    - chunk_id;
    - fallback com índice.

    Args:
        ranked_indices:
            Índices ordenados por score.
        records:
            Lista de registos correspondentes.

    Returns:
        List[int]:
            Índices únicos, preservando a ordem de prioridade.
    """
    unique_indices = []
    seen_keys = set()

    for idx in ranked_indices:
        record = records[int(idx)]
        citation = (record.get("citation_label") or "").strip()
        chunk_id = record.get("chunk_id")

        if citation:
            key = f"citation::{citation}"
        elif chunk_id is not None:
            key = f"chunk::{chunk_id}"
        else:
            key = f"idx::{idx}"

        if key not in seen_keys:
            unique_indices.append(int(idx))
            seen_keys.add(key)

    return unique_indices


def ensure_doc_coverage(
    selected: List[int],
    ranked_unique: List[int],
    records: List[Dict[str, Any]],
    adjusted_scores: np.ndarray,
    target_docs: List[str]
) -> List[int]:
    """
    Garante cobertura mínima dos documentos-alvo na seleção final.

    Se a pergunta apontar, por exemplo, para MDR + AI Act, esta função tenta
    garantir que a seleção final inclui pelo menos uma boa fonte de cada um,
    desde que o score mínimo desse documento seja aceitável.

    Isto evita casos em que um documento domina totalmente o retrieval e o outro
    desaparece, apesar de também ser relevante.

    Args:
        selected:
            Índices já selecionados.
        ranked_unique:
            Índices únicos ordenados.
        records:
            Registos disponíveis.
        adjusted_scores:
            Scores ajustados.
        target_docs:
            Documentos-alvo esperados.

    Returns:
        List[int]:
            Lista final com cobertura documental reforçada.
    """
    if not target_docs:
        return selected

    selected_set = set(selected)

    for doc_name in target_docs:
        best_idx = None
        best_score = -999.0

        for idx in ranked_unique:
            if records[idx].get("short_name") == doc_name:
                score = adjusted_scores[idx]
                if score > best_score:
                    best_score = score
                    best_idx = idx

        if best_idx is not None and best_score >= DOC_COVERAGE_MIN_SCORE and best_idx not in selected_set:
            selected.append(best_idx)
            selected_set.add(best_idx)

    selected.sort(key=lambda i: adjusted_scores[i], reverse=True)
    return selected


def select_relevant_indices(
    records: List[Dict[str, Any]],
    adjusted_scores: np.ndarray,
    plan: Dict[str, Any],
    initial_k: int = INITIAL_RETRIEVAL_K,
    min_absolute_score: float = MIN_ABSOLUTE_SCORE,
    relative_ratio: float = RELATIVE_SCORE_RATIO
) -> List[int]:
    """
    Seleciona os índices finais das fontes relevantes após scoring.

    Processo:
    1. ordenar todos os registos por score ajustado;
    2. limitar aos top-K iniciais;
    3. deduplicar;
    4. aplicar threshold dinâmico:
       - no mínimo `min_absolute_score`;
       - ou `best_score * relative_ratio`, o que for maior;
    5. garantir cobertura dos documentos-alvo.

    Args:
        records:
            Registos disponíveis.
        adjusted_scores:
            Scores ajustados de todos os registos.
        plan:
            Plano inferido da pergunta.
        initial_k:
            Número máximo de candidatos iniciais.
        min_absolute_score:
            Threshold absoluto mínimo.
        relative_ratio:
            Threshold relativo ao melhor score.

    Returns:
        List[int]:
            Índices finais selecionados.
    """
    ranked_indices = np.argsort(adjusted_scores)[::-1][:initial_k]
    ranked_unique = deduplicate_ranked_indices(ranked_indices, records)

    if not ranked_unique:
        return []

    best_score = adjusted_scores[ranked_unique[0]]
    dynamic_threshold = max(min_absolute_score, best_score * relative_ratio)

    selected = [idx for idx in ranked_unique if adjusted_scores[idx] >= dynamic_threshold]

    if not selected:
        selected = [ranked_unique[0]]

    selected = ensure_doc_coverage(
        selected=selected,
        ranked_unique=ranked_unique,
        records=records,
        adjusted_scores=adjusted_scores,
        target_docs=plan["target_docs"]
    )

    return selected


def retrieve_relevant_indices(
    question: str,
    records: List[Dict[str, Any]],
    embeddings: np.ndarray,
    embed_model: str
) -> Tuple[List[int], np.ndarray, np.ndarray, Dict[str, Any]]:
    """
    Executa o pipeline completo de retrieval semântico.

    Etapas:
    1. analisar a pergunta;
    2. gerar variantes de query;
    3. obter embedding de cada query via Ollama;
    4. calcular similaridade de cada query com todos os embeddings;
    5. combinar scores base via máximo entre queries;
    6. aplicar heurísticas regulatórias para obter scores ajustados;
    7. selecionar índices finais relevantes.

    Esta função é o ponto central de entrada do retrieval.

    Args:
        question:
            Pergunta do utilizador.
        records:
            Lista de registos normativos.
        embeddings:
            Matriz de embeddings correspondentes.
        embed_model:
            Nome do modelo de embeddings no Ollama.

    Returns:
        Tuple[List[int], np.ndarray, np.ndarray, Dict[str, Any]]:
            - índices selecionados;
            - scores base;
            - scores ajustados;
            - plano inferido da pergunta.
    """
    plan = analyze_question(question)
    queries = build_query_variants(question, plan)

    query_score_list = []

    for q in queries:
        q_embedding = ollama.embed(
            model=embed_model,
            input=q
        )["embeddings"][0]

        q_embedding = np.array(q_embedding, dtype=np.float32)
        q_scores = cosine_similarity(q_embedding, embeddings)
        query_score_list.append(q_scores)

    base_scores = np.max(np.vstack(query_score_list), axis=0)

    adjusted_scores = np.array([
        adjust_score(float(score), record, plan, question)
        for score, record in zip(base_scores, records)
    ])

    selected_indices = select_relevant_indices(
        records=records,
        adjusted_scores=adjusted_scores,
        plan=plan
    )

    return selected_indices, base_scores, adjusted_scores, plan


def truncate_text(text: str, max_chars: int = MAX_CONTEXT_CHARS_PER_SOURCE) -> str:
    """
    Trunca o texto de uma fonte para evitar contexto excessivamente grande.

    Isto é útil para:
    - controlar o tamanho do prompt enviado ao modelo;
    - manter apenas a parte mais representativa do excerto;
    - evitar custos/latência desnecessários.

    Args:
        text:
            Texto completo do chunk.
        max_chars:
            Número máximo de caracteres a manter.

    Returns:
        str:
            Texto truncado, com marcador final se necessário.
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " [...]"


def build_context(selected_indices: List[int], records: List[Dict[str, Any]]) -> str:
    """
    Constrói o contexto textual final para enviar ao modelo de chat.

    Cada fonte é formatada com:
    - número da fonte;
    - citação;
    - documento;
    - tipo de secção;
    - secção;
    - título;
    - páginas;
    - texto do chunk truncado.

    Este formato ajuda o modelo a:
    - distinguir claramente as fontes;
    - citar corretamente;
    - responder apenas com base no contexto dado.

    Args:
        selected_indices:
            Índices das fontes a incluir no contexto.
        records:
            Registos completos disponíveis.

    Returns:
        str:
            Contexto final concatenado.
    """
    parts = []

    for pos, idx in enumerate(selected_indices, start=1):
        r = records[idx]
        chunk_text = truncate_text(r.get("chunk_text", ""))

        parts.append(
            f"""
[FONTE {pos}]
Citação: {r.get('citation_label', '')}
Documento: {r.get('short_name', '')}
Tipo: {r.get('section_type', '')}
Secção: {r.get('section_number', '')}
Título: {r.get('section_title', '')}
Páginas: {r.get('page_start', '')} - {r.get('page_end', '')}

Texto:
{chunk_text}
""".strip()
        )

    return "\n\n".join(parts)