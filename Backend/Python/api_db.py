"""
Utilitários partilhados de acesso à base de dados do BridgeMedAI.

Este módulo centraliza a configuração e a criação de ligações ao SQL Server
para todos os componentes da API (auth, admin, RAG, regulatório). Anteriormente
cada módulo replicava a `get_connection` do script de ingestão; agora todos
passam a usar este helper.

As credenciais e parâmetros são lidos do `.env` do backend, com os mesmos nomes
que os scripts de ingestão já usavam:

- `DB_SERVER`
- `DB_NAME`
- `DB_TRUSTED_CONNECTION`
- `DB_ENCRYPT`
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pyodbc
from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")


DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "yes")
DB_ENCRYPT = os.getenv("DB_ENCRYPT", "yes")


def _build_connection_string() -> str:
    return (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"Trusted_Connection={DB_TRUSTED_CONNECTION};"
        f"Encrypt={DB_ENCRYPT};"
        "TrustServerCertificate=yes;"
    )


def get_connection() -> pyodbc.Connection:
    """Cria uma ligação ao SQL Server configurado no `.env` do backend."""
    return pyodbc.connect(_build_connection_string())


@contextmanager
def db_cursor(commit: bool = False) -> Iterator[pyodbc.Cursor]:
    """
    Context manager que abre ligação + cursor e garante fecho em qualquer saída.

    Usa `commit=True` para operações de escrita. Em caso de exceção faz sempre
    rollback antes de propagar o erro.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    finally:
        conn.close()
