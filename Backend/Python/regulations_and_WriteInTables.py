"""
Pipeline de ingestão documental e escrita em base de dados para o projeto BridgeMedAI.

Este módulo é responsável por transformar documentos regulatórios em PDF numa
estrutura persistida em SQL Server, preparada para fases posteriores como:
- geração de embeddings;
- retrieval semântico;
- chat RAG;
- rastreabilidade documental.

Responsabilidades principais:
- carregar configuração do projeto via `.env`;
- abrir PDFs regulatórios;
- extrair texto por página;
- limpar e normalizar o texto extraído;
- detetar secções normativas (capítulos, artigos, anexos, considerandos, etc.);
- dividir secções em subunidades mais específicas (regras, pontos, alíneas);
- aplicar chunking ao texto normativo;
- escrever documentos, secções, chunks e jobs de ingestão nas tabelas SQL.

Este ficheiro constitui a base do pipeline de preparação documental do sistema.
Tudo o que vier depois — embeddings, pesquisa semântica e geração assistida —
depende da qualidade da estrutura produzida aqui.
"""

import os
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import fitz  # PyMuPDF
import pyodbc
from dotenv import load_dotenv


# =========================================================
# 1. CARREGAR CONFIGURAÇÃO
# =========================================================
# Resolve caminhos do projeto e carrega as variáveis do ficheiro `.env`.
# Estas variáveis incluem:
# - configurações de acesso à base de dados;
# - pasta onde se encontram os PDFs regulatórios.
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
ENV_PATH = PROJECT_ROOT / "Backend" / ".env"

load_dotenv(dotenv_path=ENV_PATH)

DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "yes")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")
DOCS_ROOT = (PROJECT_ROOT / os.getenv("DOCS_ROOT", "Docs/Regulations")).resolve()


# =========================================================
# 2. LIGAÇÃO À BASE DE DADOS
# =========================================================
def get_connection():
    """
    Cria uma ligação ao SQL Server configurado no projeto.

    A ligação usa as variáveis carregadas do `.env`, incluindo:
    - servidor;
    - nome da base de dados;
    - trusted connection;
    - encriptação.

    Returns:
        pyodbc.Connection:
            Ligação ativa à base de dados.
    """
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"Trusted_Connection={DB_TRUSTED_CONNECTION};"
        f"Encrypt={DB_ENCRYPT};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def reset_regulatory_tables(short_names=("MDR", "AI_ACT")):
    """
    Remove da base de dados os documentos regulatórios indicados e todos os
    respetivos chunks, secções e jobs de ingestão.

    Isto evita duplicação quando se corre novamente o pipeline de ingestão.
    """
    if not short_names:
        return

    placeholders = ",".join(["?"] * len(short_names))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            f"""
            DELETE c
            FROM dbo.document_chunks c
            INNER JOIN dbo.documents d
                ON c.document_id = d.id
            WHERE d.short_name IN ({placeholders})
            """,
            *short_names,
        )

        cursor.execute(
            f"""
            DELETE s
            FROM dbo.document_sections s
            INNER JOIN dbo.documents d
                ON s.document_id = d.id
            WHERE d.short_name IN ({placeholders})
            """,
            *short_names,
        )

        cursor.execute(
            f"""
            DELETE j
            FROM dbo.ingestion_jobs j
            INNER JOIN dbo.documents d
                ON j.document_id = d.id
            WHERE d.short_name IN ({placeholders})
            """,
            *short_names,
        )

        cursor.execute(
            f"""
            DELETE FROM dbo.documents
            WHERE short_name IN ({placeholders})
            """,
            *short_names,
        )

        conn.commit()
        print(f"[OK] Dados antigos removidos para: {', '.join(short_names)}")

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


# =========================================================
# 3. HASH DO FICHEIRO
# =========================================================
def compute_sha256(file_path: str) -> str:
    """
    Calcula o hash SHA-256 de um ficheiro.

    Este hash permite:
    - identificar univocamente o conteúdo do PDF;
    - detetar alterações no ficheiro ao longo do tempo;
    - reforçar rastreabilidade documental.

    Args:
        file_path:
            Caminho para o ficheiro a analisar.

    Returns:
        str:
            Hash SHA-256 em formato hexadecimal.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


# =========================================================
# 4. EXTRAIR TEXTO DO PDF
# =========================================================
def extract_text_by_page(pdf_path: str) -> List[Tuple[int, str]]:
    """
    Extrai texto de um PDF página a página.

    O resultado é uma lista de tuplos:
        (número_da_página, texto_extraído)

    Esta abordagem é importante porque:
    - preserva a noção de paginação;
    - permite associar secções e chunks a páginas específicas;
    - facilita a futura citação e auditoria.

    Args:
        pdf_path:
            Caminho para o PDF regulatório.

    Returns:
        List[Tuple[int, str]]:
            Lista de páginas com respetivo texto extraído.
    """
    doc = fitz.open(pdf_path)
    pages = []

    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        text = page.get_text("text")
        pages.append((page_number + 1, text))

    doc.close()
    return pages


# =========================================================
# 5. NORMALIZAÇÃO
# =========================================================
def normalize_line(line: str) -> str:
    """
    Normaliza uma linha individual de texto.

    Faz:
    - substituição de espaços especiais;
    - redução de espaços redundantes;
    - trim de espaços no início/fim.

    Args:
        line:
            Linha de texto original.

    Returns:
        str:
            Linha normalizada.
    """
    line = (line or "").replace("\xa0", " ").replace("\u200b", " ")
    line = re.sub(r"[ \t]+", " ", line).strip()
    return line


def normalize_text_block(text: str) -> str:
    """
    Normaliza um bloco de texto multi-linha.

    Faz:
    - normalização de espaços especiais;
    - uniformização de quebras de linha;
    - remoção de linhas em branco excessivas.

    Args:
        text:
            Bloco de texto original.

    Returns:
        str:
            Texto normalizado.
    """
    text = text or ""
    text = text.replace("\xa0", " ").replace("\u200b", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def combine_broken_lines(lines: List[str]) -> List[str]:
    """
    Tenta recompor linhas partidas pelo layout do PDF.

    PDFs regulatórios frequentemente partem frases a meio devido a quebras
    visuais de linha. Esta função tenta reconstruir blocos mais coerentes.

    Critérios usados:
    - iniciar novo bloco quando encontra cabeçalhos ou itens de lista;
    - manter juntas linhas que parecem continuidade textual;
    - separar blocos quando a linha anterior termina fortemente e a seguinte
      começa como novo enunciado.

    Args:
        lines:
            Lista de linhas extraídas do PDF.

    Returns:
        List[str]:
            Lista de linhas combinadas de forma mais natural.
    """
    if not lines:
        return []

    combined = []
    buffer = ""

    def flush():
        """
        Fecha o buffer atual e envia-o para a lista final se tiver conteúdo.
        """
        nonlocal buffer
        if buffer.strip():
            combined.append(buffer.strip())
        buffer = ""

    list_like_pattern = re.compile(
    r"^(\(?[a-zA-Z0-9ivxIVX]+\)|\d+\)|\d+(?:\.\d+)*\.|-|•)\s+"
    )
    
    header_like_pattern = re.compile(
        r"^(CAP[IÍ]TULO|CHAPTER|ANEXO|ANNEX|ARTIGO|ARTICLE|Article|Regra|RULE)\b",
        re.IGNORECASE
    )

    for raw in lines:
        line = normalize_line(raw)
        if not line:
            flush()
            continue

        starts_new_block = (
            header_like_pattern.match(line) is not None
            or list_like_pattern.match(line) is not None
            or re.match(r"^\(\d+\)\s+", line) is not None
        )

        if not buffer:
            buffer = line
            continue

        prev_ends_hard = buffer.endswith((".", ":", ";"))
        current_starts_upper = bool(re.match(r"^[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]", line))
        current_starts_lower = bool(re.match(r"^[a-záàâãéêíóôõúç]", line))

        if starts_new_block:
            flush()
            buffer = line
        elif prev_ends_hard and current_starts_upper:
            flush()
            buffer = line
        elif current_starts_lower:
            buffer += " " + line
        else:
            buffer += " " + line

    flush()
    return combined


def is_noise_line(line: str) -> bool:
    """
    Identifica linhas de ruído editorial ou tipográfico do PDF.

    Exemplos:
    - cabeçalhos/rodapés do Jornal Oficial;
    - numeração de página isolada;
    - referências editoriais repetitivas.

    Estas linhas são normalmente irrelevantes para a estrutura normativa
    e devem ser ignoradas.

    Args:
        line:
            Linha a avaliar.

    Returns:
        bool:
            True se a linha for considerada ruído.
    """
    if not line:
        return True

    patterns = [
        r"^Jornal Oficial da União Europeia",
        r"^JO L de ",
        r"^PT JO L",
        r"^ELI:",
        r"^\d+/\d+$",
        r"^\d+\.\d+\.\d{4}$",
        r"^Série L$",
        r"^\(\d+\)\s+JO\s",
        r"^\(\d+\)\s+Parecer\s",
        r"^\(\d+\)\s+Posição\s",
        r"^EN Official Journal of the European Union",
        r"^Official Journal of the European Union",
        r"^\d+\s*$",
    ]

    for p in patterns:
        if re.match(p, line, re.IGNORECASE):
            return True

    return False


def is_recitals_intro(line: str) -> bool:
    """
    Verifica se uma linha corresponde à introdução dos considerandos.

    Isto é útil para ativar a deteção de recitals/considerandos no documento.

    Args:
        line:
            Linha a avaliar.

    Returns:
        bool:
            True se a linha marcar a entrada na zona de considerandos.
    """
    line_norm = normalize_line(line).lower()
    return line_norm in {
        "considerando o seguinte:",
        "considerando o seguinte",
        "whereas:",
        "whereas",
        "considering the following:",
        "considering the following",
    }


# =========================================================
# 6. DETEÇÃO DE SECÇÕES
# =========================================================
def detect_header(line: str, allow_recital: bool = False) -> Optional[Dict[str, str]]:
    """
    Tenta detetar se uma linha é um cabeçalho normativo.

    Cabeçalhos reconhecidos:
    - capítulos;
    - anexos;
    - artigos;
    - considerandos (se `allow_recital=True`).

    O retorno inclui:
    - tipo de secção;
    - número/identificador;
    - cabeçalho normalizado;
    - texto inline adicional, quando exista.

    Args:
        line:
            Linha a avaliar.
        allow_recital:
            Indica se os considerandos já podem ser reconhecidos.

    Returns:
        Optional[Dict[str, str]]:
            Dicionário com metadata da secção, ou `None` se não for cabeçalho.
    """
    line_norm = normalize_line(line)

    m = re.match(r"^(CAP[IÍ]TULO|CHAPTER)\s+([IVXLC\d]+)$", line_norm, re.IGNORECASE)
    if m:
        label = "CAPÍTULO" if m.group(1).lower().startswith("cap") else "CHAPTER"
        return {
            "section_type": "chapter",
            "section_number": f"{label} {m.group(2)}",
            "header": f"{label} {m.group(2)}",
            "inline_text": ""
        }

    m = re.match(r"^(ANEXO|ANNEX)\s+([IVXLC\d]+)(?:\s+(.*))?$", line_norm, re.IGNORECASE)
    if m:
        label = "ANEXO" if m.group(1).lower().startswith("anexo") else "ANNEX"
        extra = (m.group(3) or "").strip()
        return {
            "section_type": "annex",
            "section_number": f"{label} {m.group(2)}",
            "header": f"{label} {m.group(2)}",
            "inline_text": extra
        }

    m = re.match(
        r"^(Artigo|ARTICLE|Article)\s+(\d+)(?:\s*[\.\u00BA\u00B0oºª]*)?$",
        line_norm,
        re.IGNORECASE
    )
    if m:
        label = "Artigo" if m.group(1).lower().startswith("artigo") else "Article"
        return {
            "section_type": "article",
            "section_number": f"{label} {m.group(2)}",
            "header": f"{label} {m.group(2)}",
            "inline_text": ""
        }

    if allow_recital:
        m = re.match(r"^\((\d+)\)\s*(.*)$", line_norm)
        if m:
            return {
                "section_type": "recital",
                "section_number": f"({m.group(1)})",
                "header": f"({m.group(1)})",
                "inline_text": (m.group(2) or "").strip()
            }

    return None


# =========================================================
# 7. DIVIDIR EM SECÇÕES
# =========================================================
def split_into_sections_from_pages(pages, short_name: str):
    """
    Divide o texto integral do documento em secções normativas estruturadas.

    O algoritmo percorre página a página e linha a linha, tentando:
    - ignorar ruído;
    - reconhecer cabeçalhos normativos;
    - agrupar texto por secção;
    - preservar intervalo de páginas;
    - criar uma secção de preâmbulo, quando aplicável.

    Se não forem detetadas secções formais, o documento inteiro pode ser
    guardado como uma secção única do tipo `document`.

    Args:
        pages:
            Lista de páginas e respetivo texto.
        short_name:
            Nome curto do documento (ex.: MDR, AI_ACT).

    Returns:
        list:
            Lista de dicionários com secções estruturadas.
    """
    sections = []
    current = None
    preamble_lines = []
    section_order = 0
    allow_recitals = False
    current_annex = None

    def flush_current():
        """
        Fecha a secção atualmente em construção e envia-a para a lista final.
        """
        nonlocal current
        if current is None:
            return

        processed_lines = combine_broken_lines(current["lines"])
        raw_text = normalize_text_block("\n".join(processed_lines))
        section_title = current["section_title"] or current["section_number"]

        if raw_text:
            sections.append({
                "section_type": current["section_type"],
                "section_number": current["section_number"],
                "section_title": section_title,
                "raw_text": raw_text,
                "section_order": current["section_order"],
                "page_start": current["page_start"],
                "page_end": current["page_end"],
                "parent_annex": current.get("parent_annex"),
            })

        current = None

    for page_number, page_text in pages:
        for raw_line in page_text.splitlines():
            line = normalize_line(raw_line)

            if not line or is_noise_line(line):
                continue

            if is_recitals_intro(line):
                allow_recitals = True
                if current is None:
                    preamble_lines.append(line)
                else:
                    current["lines"].append(line)
                continue

            header = detect_header(line, allow_recital=allow_recitals)

            if header:
                flush_current()

                # Se já havia linhas antes do primeiro cabeçalho, podem ser
                # guardadas como preâmbulo.
                if preamble_lines:
                    preamble_processed = combine_broken_lines(preamble_lines)
                    preamble_text = normalize_text_block("\n".join(preamble_processed))

                    if preamble_text:
                        sections.append({
                            "section_type": "preamble",
                            "section_number": "PREAMBULO",
                            "section_title": "Preâmbulo",
                            "raw_text": preamble_text,
                            "section_order": section_order,
                            "page_start": 1,
                            "page_end": page_number
                        })
                        section_order += 1

                    preamble_lines = []
                
                if header["section_type"] == "annex":
                    current_annex = header["section_number"]
                
                current = {
                    "section_type": header["section_type"],
                    "section_number": header["section_number"],
                    "section_title": None,
                    "lines": [header["header"]],
                    "section_order": section_order,
                    "page_start": page_number,
                    "page_end": page_number,
                    "parent_annex": current_annex,
                }
                section_order += 1

                if header["section_type"] == "recital":
                    current["section_title"] = f"Considerando {header['section_number']}"
                    if header["inline_text"]:
                        current["lines"].append(header["inline_text"])

                elif header["inline_text"]:
                    current["section_title"] = header["inline_text"]
                    current["lines"].append(header["inline_text"])

                continue

            if current is None:
                preamble_lines.append(line)
                continue

            current["page_end"] = page_number

            # Heurística para apanhar títulos curtos logo após cabeçalhos de
            # capítulo, artigo ou anexo.
            if current["section_title"] is None and current["section_type"] in {"chapter", "article", "annex"}:
                if len(line) <= 180 and not detect_header(line, allow_recital=False):
                    current["section_title"] = line
                    current["lines"].append(line)
                    continue

            current["lines"].append(line)

    flush_current()

    # Fallback: se nada foi detetado como secção, guarda o documento inteiro.
    if not sections and preamble_lines:
        preamble_processed = combine_broken_lines(preamble_lines)
        full_text = normalize_text_block("\n".join(preamble_processed))

        if full_text:
            sections.append({
                "section_type": "document",
                "section_number": short_name,
                "section_title": f"{short_name} Full Text",
                "raw_text": full_text,
                "section_order": 0,
                "page_start": 1,
                "page_end": len(pages)
            })

    return sections


# =========================================================
# 8. SUBUNIDADES NORMATIVAS
# =========================================================
def split_section_into_subunits(section: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Tenta dividir uma secção longa em subunidades mais úteis para retrieval.

    Estratégias:
    - separar por `Regra X / Rule X`;
    - separar pontos numerados (`1.`, `2.`, `3.`...);
    - manter alíneas como parte do ponto atual.

    Isto é especialmente útil para:
    - anexos normativos extensos;
    - secções de classificação;
    - conteúdo que ficaria demasiado genérico se tratado como um bloco único.

    Args:
        section:
            Dicionário com a secção base.

    Returns:
        List[Dict[str, str]]:
            Lista de subunidades ou, se não houver divisão útil, uma única unidade.
    """
    raw_text = normalize_text_block(section["raw_text"])
    if not raw_text:
        return []

    lines = [normalize_line(line) for line in raw_text.split("\n") if normalize_line(line)]
    lines = combine_broken_lines(lines)

    rule_pattern = re.compile(
    r"^(?:\d+(?:\.\d+)*\.\s*)?(Regra|RULE)\s+(?:n\.?\s*[ºo°]?\s*)?(\d+)(?:\s*[—\-–:]?\s*(.*))?$",
    re.IGNORECASE,
    )
    
    numbered_pattern = re.compile(r"^(\d+)\.\s+(.*)$")
    alpha_pattern = re.compile(r"^\(([a-z])\)\s+(.*)$", re.IGNORECASE)

    has_rule_headers = any(rule_pattern.match(line) for line in lines)
    has_numbered_blocks = sum(1 for line in lines if numbered_pattern.match(line)) >= 3

    if has_rule_headers:
        units = []
        current = None

        def flush_rule():
            """
            Fecha a regra atualmente em construção.
            """
            nonlocal current
            if current and current["lines"]:
                units.append({
                    "unit_type": "rule",
                    "unit_number": current["unit_number"],
                    "unit_title": current["unit_title"] or current["unit_number"],
                    "raw_text": normalize_text_block("\n".join(current["lines"]))
                })
            current = None

        for line in lines:
            m = rule_pattern.match(line)
            if m:
                flush_rule()
                label = "Regra" if m.group(1).lower().startswith("regra") else "Rule"
                current = {
                    "unit_number": f"{label} {m.group(2)}",
                    "unit_title": (m.group(3) or "").strip() or f"{label} {m.group(2)}",
                    "lines": [line],
                }
            elif current is not None:
                current["lines"].append(line)

        flush_rule()
        return units

    if has_numbered_blocks and section["section_type"] in {"article", "annex"}:
        units = []
        current = None

        def flush_numbered():
            """
            Fecha o ponto numerado atualmente em construção.
            """
            nonlocal current
            if current and current["lines"]:
                units.append({
                    "unit_type": "point",
                    "unit_number": current["unit_number"],
                    "unit_title": current["unit_title"] or current["unit_number"],
                    "raw_text": normalize_text_block("\n".join(current["lines"]))
                })
            current = None

        for line in lines:
            m_num = numbered_pattern.match(line)
            m_alpha = alpha_pattern.match(line)

            if m_num:
                flush_numbered()
                current = {
                    "unit_number": f"Ponto {m_num.group(1)}",
                    "unit_title": m_num.group(2).strip()[:120],
                    "lines": [line],
                }
            elif m_alpha and current is not None:
                current["lines"].append(line)
            elif current is not None:
                current["lines"].append(line)

        flush_numbered()
        if units:
            return units

    return [{
        "unit_type": section["section_type"],
        "unit_number": section["section_number"],
        "unit_title": section["section_title"],
        "raw_text": raw_text,
    }]


# =========================================================
# 9. CHUNKING
# =========================================================
def split_long_paragraph(paragraph: str, max_chars: int, overlap: int) -> List[str]:
    """
    Divide um parágrafo demasiado longo em chunks menores.

    Estratégia:
    - tenta primeiro dividir por frases;
    - se uma frase for ainda demasiado longa, usa corte por janela com overlap.

    Args:
        paragraph:
            Parágrafo a dividir.
        max_chars:
            Tamanho máximo desejado por chunk.
        overlap:
            Sobreposição entre fragmentos quando há corte forçado.

    Returns:
        List[str]:
            Lista de fragmentos menores.
    """
    paragraph = normalize_text_block(paragraph)
    if len(paragraph) <= max_chars:
        return [paragraph] if paragraph else []

    sentences = re.split(r"(?<=[\.\!\?\:;])\s+", paragraph)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence

        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)

            if len(sentence) <= max_chars:
                current = sentence
            else:
                start = 0
                while start < len(sentence):
                    end = start + max_chars
                    piece = sentence[start:end].strip()
                    if piece:
                        chunks.append(piece)
                    if end >= len(sentence):
                        break
                    start = max(0, end - overlap)
                current = ""

    if current:
        chunks.append(current)

    return chunks


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    """
    Divide texto normativo em chunks adequados para embeddings e retrieval.

    Estratégia:
    - normaliza o texto;
    - separa por blocos/parágrafos;
    - tenta manter blocos juntos enquanto couberem no limite;
    - usa overlap para preservar continuidade contextual entre chunks.

    Args:
        text:
            Texto a dividir.
        max_chars:
            Tamanho máximo por chunk.
        overlap:
            Número de caracteres de sobreposição entre chunks adjacentes.

    Returns:
        List[str]:
            Lista final de chunks limpos e deduplicados.
    """
    text = normalize_text_block(text)
    if not text:
        return []

    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if not blocks:
        blocks = [text]

    normalized_blocks = []
    for block in blocks:
        lines = [normalize_line(line) for line in block.split("\n") if normalize_line(line)]
        merged = combine_broken_lines(lines)
        if merged:
            normalized_blocks.append("\n".join(merged))

    chunks = []
    current = ""

    def append_chunk(chunk: str):
        """
        Adiciona um chunk final à lista, se tiver conteúdo útil.
        """
        chunk = normalize_text_block(chunk)
        if chunk:
            chunks.append(chunk)

    for block in normalized_blocks:
        block = normalize_text_block(block)

        if len(block) > max_chars:
            if current:
                append_chunk(current)
                current = ""

            for piece in split_long_paragraph(block, max_chars=max_chars, overlap=overlap):
                append_chunk(piece)
            continue

        candidate = f"{current}\n\n{block}".strip() if current else block

        if len(candidate) <= max_chars:
            current = candidate
        else:
            append_chunk(current)

            if overlap > 0 and current:
                tail = current[-overlap:].strip()
                if tail and len(f"{tail}\n\n{block}") <= max_chars:
                    current = f"{tail}\n\n{block}".strip()
                else:
                    current = block
            else:
                current = block

    if current:
        append_chunk(current)

    final_chunks = []
    last = None
    for ch in chunks:
        ch = normalize_text_block(ch)
        if not ch:
            continue
        if last == ch:
            continue
        final_chunks.append(ch)
        last = ch

    return final_chunks


# =========================================================
# 10. INSERÇÕES SQL
# =========================================================
def insert_document(cursor, title, short_name, version_label, source_url, file_path, sha256_hash, language="en"):
    """
    Insere um documento na tabela `dbo.documents`.

    Args:
        cursor:
            Cursor ativo da ligação SQL.
        title:
            Título completo do documento.
        short_name:
            Nome curto do documento.
        version_label:
            Versão/identificação normativa.
        source_url:
            URL oficial de origem do documento.
        file_path:
            Caminho local do ficheiro PDF.
        sha256_hash:
            Hash SHA-256 do ficheiro.
        language:
            Idioma do documento.

    Returns:
        int:
            ID inserido do documento.
    """
    cursor.execute(
        """
        INSERT INTO dbo.documents (
            title, short_name, version_label, source_url, file_path, sha256_hash, language
        )
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        title, short_name, version_label, source_url, file_path, sha256_hash, language
    )
    row = cursor.fetchone()
    return row[0]


def insert_ingestion_job(cursor, document_id, status="running"):
    """
    Regista o início de um job de ingestão.

    Isto permite rastrear:
    - quando começou a ingestão;
    - se ficou concluída;
    - se falhou e com que erro.

    Args:
        cursor:
            Cursor SQL.
        document_id:
            ID do documento associado.
        status:
            Estado inicial do job.

    Returns:
        int:
            ID do job criado.
    """
    cursor.execute(
        """
        INSERT INTO dbo.ingestion_jobs (
            document_id, status, started_at
        )
        OUTPUT INSERTED.id
        VALUES (?, ?, SYSUTCDATETIME())
        """,
        document_id, status
    )
    row = cursor.fetchone()
    return row[0]


def update_ingestion_job(cursor, job_id, status, error_message=None):
    """
    Atualiza o estado final de um job de ingestão.

    Args:
        cursor:
            Cursor SQL.
        job_id:
            ID do job a atualizar.
        status:
            Novo estado do job.
        error_message:
            Mensagem de erro, caso exista.

    Returns:
        None
    """
    cursor.execute(
        """
        UPDATE dbo.ingestion_jobs
        SET status = ?,
            finished_at = SYSUTCDATETIME(),
            error_message = ?
        WHERE id = ?
        """,
        status, error_message, job_id
    )


def insert_section(cursor, document_id, section_type, section_number, section_title, raw_text,
                   section_order=None, page_start=None, page_end=None):
    """
    Insere uma secção normativa na tabela `dbo.document_sections`.

    Args:
        cursor:
            Cursor SQL.
        document_id:
            ID do documento pai.
        section_type:
            Tipo de secção.
        section_number:
            Número/identificador da secção.
        section_title:
            Título da secção.
        raw_text:
            Texto bruto da secção.
        section_order:
            Ordem sequencial da secção no documento.
        page_start:
            Página inicial.
        page_end:
            Página final.

    Returns:
        int:
            ID da secção inserida.
    """
    cursor.execute(
        """
        INSERT INTO dbo.document_sections (
            document_id, section_type, section_number, section_title, raw_text,
            section_order, page_start, page_end
        )
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        document_id, section_type, section_number, section_title, raw_text,
        section_order, page_start, page_end
    )
    row = cursor.fetchone()
    return row[0]


def insert_chunk(cursor, document_id, section_id, chunk_index, chunk_text_value, citation_label,
                 page_start=None, page_end=None):
    """
    Insere um chunk textual na tabela `dbo.document_chunks`.

    O campo `token_count` é atualmente aproximado pelo número de palavras.

    Args:
        cursor:
            Cursor SQL.
        document_id:
            ID do documento pai.
        section_id:
            ID da secção pai.
        chunk_index:
            Índice sequencial do chunk dentro da secção.
        chunk_text_value:
            Texto do chunk.
        citation_label:
            Citação curta associada ao chunk.
        page_start:
            Página inicial.
        page_end:
            Página final.

    Returns:
        None
    """
    token_count_approx = max(1, len(chunk_text_value.split()))

    cursor.execute(
        """
        INSERT INTO dbo.document_chunks (
            document_id, section_id, chunk_index, chunk_text, token_count,
            page_start, page_end, citation_label
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        document_id, section_id, chunk_index, chunk_text_value, token_count_approx,
        page_start, page_end, citation_label
    )


# =========================================================
# 11. PIPELINE PRINCIPAL
# =========================================================
def build_citation_label(short_name: str, section: Dict[str, str], unit: Dict[str, str]) -> str:
    section_number = (section.get("section_number") or "").strip()
    section_title = (section.get("section_title") or "").strip()
    parent_annex = (section.get("parent_annex") or "").strip()
    unit_type = (unit.get("unit_type") or "").strip()
    unit_number = (unit.get("unit_number") or "").strip()

    if unit_type == "rule" and unit_number:
        parent = parent_annex

        # Fallback específico para regras de classificação MDR.
        if not parent and short_name == "MDR":
            text = f"{section_number} {section_title}".lower()
            if "regras de classificação" in text or "regras de classificacao" in text:
                parent = "ANEXO VIII"

        if parent:
            return f"{short_name} {parent} {unit_number}"

        return f"{short_name} {section_number} {unit_number}".strip()

    if unit_type == "point" and unit_number and unit_number != section_number:
        return f"{short_name} {section_number} {unit_number}".strip()

    if section_number:
        return f"{short_name} {section_number}"

    return f"{short_name} SEM_SECCAO"


def ingest_regulation(
    pdf_path: str,
    title: str,
    short_name: str,
    version_label: str,
    source_url: str = None,
    language: str = "en"
):
    """
    Executa a ingestão completa de um regulamento PDF para a base de dados.

    Pipeline:
    1. validar existência do ficheiro;
    2. calcular hash SHA-256;
    3. inserir documento na base de dados;
    4. criar job de ingestão;
    5. extrair texto por página;
    6. dividir em secções;
    7. inserir secções;
    8. dividir em subunidades;
    9. gerar chunks;
    10. inserir chunks;
    11. marcar o job como concluído.

    Em caso de erro:
    - faz rollback;
    - tenta marcar o job como failed;
    - propaga a exceção.

    Args:
        pdf_path:
            Caminho do PDF.
        title:
            Título completo do regulamento.
        short_name:
            Nome curto do regulamento.
        version_label:
            Identificação da versão normativa.
        source_url:
            URL oficial de origem.
        language:
            Idioma do documento.

    Returns:
        None

    Raises:
        FileNotFoundError:
            Se o ficheiro PDF não existir.
        Exception:
            Propaga quaisquer erros ocorridos durante a ingestão.
    """
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"Ficheiro não encontrado: {pdf_path}")

    sha256_hash = compute_sha256(pdf_path)

    conn = get_connection()
    cursor = conn.cursor()

    document_id = None
    job_id = None

    try:
        document_id = insert_document(
            cursor=cursor,
            title=title,
            short_name=short_name,
            version_label=version_label,
            source_url=source_url,
            file_path=pdf_path,
            sha256_hash=sha256_hash,
            language=language
        )

        job_id = insert_ingestion_job(cursor, document_id=document_id, status="running")

        pages = extract_text_by_page(pdf_path)
        sections = split_into_sections_from_pages(pages, short_name=short_name)

        print(f"[INFO] {short_name}: {len(sections)} secções encontradas")

        total_chunks = 0
        db_section_order = 0

        for section in sections:
            subunits = split_section_into_subunits(section)

            if not subunits:
                continue

            for unit in subunits:
                unit_type = unit.get("unit_type") or section["section_type"]
                unit_number = unit.get("unit_number") or section["section_number"]
                unit_title = unit.get("unit_title") or section["section_title"]
                unit_raw_text = unit.get("raw_text") or section["raw_text"]

                # Se for uma subunidade real, gravamos a subunidade como secção própria.
                # Assim a SQL/Chroma passa a ter:
                # section_type = rule
                # section_number = Regra 10
                # citation_label = MDR ANEXO VIII Regra 10
                is_subunit = (
                    unit_type != section["section_type"]
                    or unit_number != section["section_number"]
                )

                section_id = insert_section(
                    cursor=cursor,
                    document_id=document_id,
                    section_type=unit_type if is_subunit else section["section_type"],
                    section_number=unit_number if is_subunit else section["section_number"],
                    section_title=unit_title if is_subunit else section["section_title"],
                    raw_text=unit_raw_text,
                    section_order=db_section_order,
                    page_start=section["page_start"],
                    page_end=section["page_end"],
                )
                db_section_order += 1

                chunks = chunk_text(unit_raw_text, max_chars=1200, overlap=150)

                for chunk_counter, ch in enumerate(chunks):
                    citation_label = build_citation_label(short_name, section, unit)

                    insert_chunk(
                        cursor=cursor,
                        document_id=document_id,
                        section_id=section_id,
                        chunk_index=chunk_counter,
                        chunk_text_value=ch,
                        citation_label=citation_label,
                        page_start=section["page_start"],
                        page_end=section["page_end"],
                    )

                    total_chunks += 1

        update_ingestion_job(cursor, job_id=job_id, status="completed", error_message=None)

        conn.commit()
        print(f"[OK] Ingestão concluída com sucesso para: {title}")
        print(f"[INFO] {short_name}: {total_chunks} chunks inseridos")

    except Exception as e:
        conn.rollback()

        if job_id is not None:
            try:
                update_ingestion_job(cursor, job_id=job_id, status="failed", error_message=str(e))
                conn.commit()
            except Exception:
                pass

        print(f"[ERRO] Falha na ingestão: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


# =========================================================
# 12. EXECUÇÃO MANUAL
# =========================================================
if __name__ == "__main__":
    reset_regulatory_tables(short_names=("MDR", "AI_ACT"))

    ingest_regulation(
        pdf_path=str(DOCS_ROOT / "MDR.pdf"),
        title="Medical Device Regulation",
        short_name="MDR",
        version_label="EU 2017/745",
        source_url="https://eur-lex.europa.eu/legal-content/PT/TXT/PDF/?uri=CELEX:32017R0745",
        language="pt"
    )

    ingest_regulation(
        pdf_path=str(DOCS_ROOT / "AI_ACT.pdf"),
        title="EU AI Act",
        short_name="AI_ACT",
        version_label="2024/1689",
        source_url="https://eur-lex.europa.eu/legal-content/PT/TXT/PDF/?uri=OJ:L_202401689",
        language="pt"
    )