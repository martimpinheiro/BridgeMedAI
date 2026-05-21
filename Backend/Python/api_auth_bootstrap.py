"""
Bootstrap do sistema de autenticação do BridgeMedAI.

Este módulo é responsável por:

- criar (ou atualizar) as tabelas necessárias para o sistema de autenticação,
  autorização e convites no SQL Server configurado no `.env`;
- expor um comando de linha para criar o **primeiro** administrador do sistema
  (seed idempotente — se já existir algum admin, o comando avisa e não cria
  novo registo).

Tabelas criadas (schema `dbo`):

- `auth_users`             — conta base de qualquer utilizador (user, especialista, admin)
- `specialist_profiles`    — detalhes profissionais do especialista
- `specialist_credentials` — documentos comprovativos submetidos pelo especialista
- `admin_invites`          — convites gerados por admins (token guardado em hash)
- `user_notifications`     — notificações persistidas (aprovação/rejeição, etc.)

Uso:

    # Criar/atualizar o schema
    python api_auth_bootstrap.py --init

    # Seed do primeiro admin (idempotente)
    python api_auth_bootstrap.py --seed-admin --email admin@exemplo.pt --password SuperSecret123 --name "Admin BridgeMedAI"

    # Tudo de uma vez
    python api_auth_bootstrap.py --init --seed-admin --email ... --password ...
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from api_db import db_cursor


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------
DDL_STATEMENTS = [
    # --- auth_users -----------------------------------------------------------
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'auth_users' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.auth_users (
            id               UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
            email            NVARCHAR(320)    NOT NULL UNIQUE,
            password_hash    NVARCHAR(255)    NOT NULL,
            full_name        NVARCHAR(200)    NOT NULL,
            role             NVARCHAR(20)     NOT NULL,
            status           NVARCHAR(20)     NOT NULL,
            created_at       DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
            updated_at       DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
            CONSTRAINT CK_auth_users_role CHECK (role IN ('user','specialist','admin')),
            CONSTRAINT CK_auth_users_status CHECK (status IN ('active','pending','rejected'))
        );
        CREATE INDEX IX_auth_users_role_status ON dbo.auth_users(role, status);
    END
    """,

    # --- specialist_profiles --------------------------------------------------
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'specialist_profiles' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.specialist_profiles (
            user_id           UNIQUEIDENTIFIER NOT NULL PRIMARY KEY
                                FOREIGN KEY REFERENCES dbo.auth_users(id) ON DELETE CASCADE,
            specialty         NVARCHAR(200)    NULL,
            institution       NVARCHAR(200)    NULL,
            country           NVARCHAR(100)    NULL,
            rejection_reason  NVARCHAR(MAX)    NULL,
            reviewed_at       DATETIME2        NULL,
            reviewed_by       UNIQUEIDENTIFIER NULL
                                FOREIGN KEY REFERENCES dbo.auth_users(id)
        );
    END
    ELSE
    BEGIN
        -- Migração: relaxar NOT NULL nas 3 colunas quando a tabela já existia
        -- (narrativa do especialista mudou: já não é profissional médico)
        IF COL_LENGTH('dbo.specialist_profiles', 'specialty') IS NOT NULL
           AND COLUMNPROPERTY(OBJECT_ID('dbo.specialist_profiles'), 'specialty', 'AllowsNull') = 0
        BEGIN
            ALTER TABLE dbo.specialist_profiles ALTER COLUMN specialty NVARCHAR(200) NULL;
        END
        IF COL_LENGTH('dbo.specialist_profiles', 'institution') IS NOT NULL
           AND COLUMNPROPERTY(OBJECT_ID('dbo.specialist_profiles'), 'institution', 'AllowsNull') = 0
        BEGIN
            ALTER TABLE dbo.specialist_profiles ALTER COLUMN institution NVARCHAR(200) NULL;
        END
        IF COL_LENGTH('dbo.specialist_profiles', 'country') IS NOT NULL
           AND COLUMNPROPERTY(OBJECT_ID('dbo.specialist_profiles'), 'country', 'AllowsNull') = 0
        BEGIN
            ALTER TABLE dbo.specialist_profiles ALTER COLUMN country NVARCHAR(100) NULL;
        END
    END
    """,

    # --- specialist_credentials ----------------------------------------------
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'specialist_credentials' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.specialist_credentials (
            id                 UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
            user_id            UNIQUEIDENTIFIER NOT NULL
                                 FOREIGN KEY REFERENCES dbo.auth_users(id) ON DELETE CASCADE,
            file_path          NVARCHAR(500)    NOT NULL,
            original_filename  NVARCHAR(255)    NOT NULL,
            mime_type          NVARCHAR(100)    NOT NULL,
            size_bytes         BIGINT           NOT NULL,
            submission_round   INT              NOT NULL DEFAULT 1,
            uploaded_at        DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
        );
        CREATE INDEX IX_specialist_credentials_user ON dbo.specialist_credentials(user_id, submission_round);
    END
    """,

    # --- admin_invites --------------------------------------------------------
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'admin_invites' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.admin_invites (
            id           UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
            token_hash   NVARCHAR(128)    NOT NULL UNIQUE,
            created_by   UNIQUEIDENTIFIER NOT NULL
                          FOREIGN KEY REFERENCES dbo.auth_users(id),
            created_at   DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
            expires_at   DATETIME2        NOT NULL,
            used_at      DATETIME2        NULL,
            used_by      UNIQUEIDENTIFIER NULL
                          FOREIGN KEY REFERENCES dbo.auth_users(id),
            note         NVARCHAR(255)    NULL
        );
        CREATE INDEX IX_admin_invites_state ON dbo.admin_invites(used_at, expires_at);
    END
    """,

    # --- user_notifications ---------------------------------------------------
    """
    IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'user_notifications' AND schema_id = SCHEMA_ID('dbo'))
    BEGIN
        CREATE TABLE dbo.user_notifications (
            id         UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
            user_id    UNIQUEIDENTIFIER NOT NULL
                        FOREIGN KEY REFERENCES dbo.auth_users(id) ON DELETE CASCADE,
            kind       NVARCHAR(40)     NOT NULL,
            title      NVARCHAR(200)    NOT NULL,
            body       NVARCHAR(MAX)    NULL,
            created_at DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
            read_at    DATETIME2        NULL
        );
        CREATE INDEX IX_user_notifications_user ON dbo.user_notifications(user_id, created_at DESC);
    END
    """,
]


def init_schema() -> None:
    """Aplica o DDL (idempotente). Executa uma statement de cada vez."""
    with db_cursor(commit=True) as cur:
        for sql in DDL_STATEMENTS:
            cur.execute(sql)
    print("[auth_bootstrap] Schema de autenticação criado/atualizado.")


# ---------------------------------------------------------------------------
# Seed do primeiro admin
# ---------------------------------------------------------------------------
def _has_any_admin() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT TOP 1 id FROM dbo.auth_users WHERE role = 'admin'")
        return cur.fetchone() is not None


def seed_first_admin(email: str, password: str, full_name: str) -> Optional[str]:
    """
    Cria o primeiro administrador se ainda não existir nenhum.

    Devolve o `id` do novo admin ou `None` se já existia admin.
    A função é idempotente: chamadas repetidas não criam múltiplos admins.
    """
    # Import tardio para evitar ciclo caso o módulo seja usado só para DDL.
    from api_auth_service import hash_password

    if _has_any_admin():
        print("[auth_bootstrap] Já existe pelo menos um admin — nada a fazer.")
        return None

    password_hash = hash_password(password)

    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO dbo.auth_users (email, password_hash, full_name, role, status)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, 'admin', 'active')
            """,
            email.strip().lower(),
            password_hash,
            full_name.strip(),
        )
        row = cur.fetchone()
        user_id = str(row[0]) if row else None

    print(f"[auth_bootstrap] Primeiro admin criado: {email} ({user_id}).")
    return user_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap do sistema de autenticação do BridgeMedAI.")
    parser.add_argument("--init", action="store_true", help="Criar/atualizar o schema no SQL Server.")
    parser.add_argument("--seed-admin", action="store_true", help="Criar o primeiro administrador (idempotente).")
    parser.add_argument("--email", type=str, help="Email do primeiro admin (obrigatório com --seed-admin).")
    parser.add_argument("--password", type=str, help="Password do primeiro admin (obrigatório com --seed-admin).")
    parser.add_argument("--name", type=str, default="Admin BridgeMedAI", help="Nome do primeiro admin.")
    args = parser.parse_args()

    if not args.init and not args.seed_admin:
        parser.print_help()
        sys.exit(1)

    if args.init:
        init_schema()

    if args.seed_admin:
        if not args.email or not args.password:
            print("Erro: --seed-admin requer --email e --password.", file=sys.stderr)
            sys.exit(2)
        seed_first_admin(email=args.email, password=args.password, full_name=args.name)


if __name__ == "__main__":
    _cli()
