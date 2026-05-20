-- ===========================================================================
-- BridgeMedAI — Context Memory schema (Fase 3 do Regulatory Documentation Copilot)
--
-- Quatro tabelas aditivas, todas com IF NOT EXISTS (idempotente).
-- O `init_context_memory_schema()` em api_context_memory.py executa este DDL
-- no startup da API.
--
-- Modelo:
--   product_profiles      — uma entrada por dispositivo/conversa (1:N com user)
--   extracted_fields      — key-value de campos canónicos do produto
--   document_instances    — instâncias de templates iniciadas pelo utilizador
--   documentation_state   — snapshot agregado (1:1 com product_profiles)
-- ===========================================================================
USE BridgeMedAI;
GO

-- ---------------------------------------------------------------------------
-- product_profiles
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'product_profiles' AND schema_id = SCHEMA_ID('dbo')
)
BEGIN
    CREATE TABLE dbo.product_profiles (
        id                UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
        user_id           UNIQUEIDENTIFIER NOT NULL,
        conversation_id   NVARCHAR(100)    NULL,
        name              NVARCHAR(255)    NULL,
        mdr_class         NVARCHAR(20)     NULL,
        ai_system_flag    BIT              NULL,
        summary           NVARCHAR(MAX)    NULL,
        created_at        DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at        DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_product_profiles_mdr_class
            CHECK (mdr_class IS NULL OR mdr_class IN ('I','IIa','IIb','III'))
    );

    CREATE INDEX IX_product_profiles_user
        ON dbo.product_profiles(user_id, updated_at DESC);

    CREATE INDEX IX_product_profiles_conversation
        ON dbo.product_profiles(conversation_id);
END
GO

-- ---------------------------------------------------------------------------
-- extracted_fields
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'extracted_fields' AND schema_id = SCHEMA_ID('dbo')
)
BEGIN
    CREATE TABLE dbo.extracted_fields (
        id                  UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
        product_profile_id  UNIQUEIDENTIFIER NOT NULL,
        field_key           NVARCHAR(120)    NOT NULL,
        field_value         NVARCHAR(MAX)    NULL,
        source              NVARCHAR(30)     NOT NULL DEFAULT 'manual',
        confidence          FLOAT            NULL,
        created_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_extracted_fields_profile
            FOREIGN KEY (product_profile_id)
            REFERENCES dbo.product_profiles(id) ON DELETE CASCADE,
        CONSTRAINT UQ_extracted_fields_profile_key
            UNIQUE (product_profile_id, field_key),
        CONSTRAINT CK_extracted_fields_source
            CHECK (source IN ('conversation','manual','document','analysis','llm'))
    );

    CREATE INDEX IX_extracted_fields_profile
        ON dbo.extracted_fields(product_profile_id);
END
GO

-- ---------------------------------------------------------------------------
-- document_instances
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'document_instances' AND schema_id = SCHEMA_ID('dbo')
)
BEGIN
    CREATE TABLE dbo.document_instances (
        id                  UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
        product_profile_id  UNIQUEIDENTIFIER NOT NULL,
        template_id         NVARCHAR(64)     NOT NULL,
        state               NVARCHAR(20)     NOT NULL DEFAULT 'draft',
        file_path           NVARCHAR(500)    NULL,
        download_name       NVARCHAR(255)    NULL,
        notes               NVARCHAR(MAX)    NULL,
        last_review_at      DATETIME2        NULL,
        created_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at          DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_document_instances_profile
            FOREIGN KEY (product_profile_id)
            REFERENCES dbo.product_profiles(id) ON DELETE CASCADE,
        CONSTRAINT CK_document_instances_state
            CHECK (state IN ('draft','partial','awaiting','reviewed','approved','exported'))
    );

    CREATE INDEX IX_document_instances_profile
        ON dbo.document_instances(product_profile_id, updated_at DESC);

    CREATE INDEX IX_document_instances_template
        ON dbo.document_instances(template_id);
END
GO

-- ---------------------------------------------------------------------------
-- documentation_state
-- ---------------------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.tables
    WHERE name = 'documentation_state' AND schema_id = SCHEMA_ID('dbo')
)
BEGIN
    CREATE TABLE dbo.documentation_state (
        product_profile_id        UNIQUEIDENTIFIER NOT NULL PRIMARY KEY,
        missing_information_json  NVARCHAR(MAX)    NULL,
        pending_sections_json     NVARCHAR(MAX)    NULL,
        progress_percent          INT              NULL,
        notes                     NVARCHAR(MAX)    NULL,
        updated_at                DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT FK_documentation_state_profile
            FOREIGN KEY (product_profile_id)
            REFERENCES dbo.product_profiles(id) ON DELETE CASCADE
    );
END
GO
