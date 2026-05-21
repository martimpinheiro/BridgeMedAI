USE [BridgeMedAI];
GO

SELECT
    t.name AS table_name,
    c.column_id,
    c.name AS column_name,
    ty.name AS data_type,
    CASE 
        WHEN ty.name IN ('nvarchar', 'nchar') AND c.max_length > 0 THEN c.max_length / 2
        WHEN ty.name IN ('varchar', 'char') AND c.max_length > 0 THEN c.max_length
        WHEN c.max_length = -1 THEN -1
        ELSE c.max_length
    END AS max_length_chars,
    c.is_nullable,
    c.is_identity,
    dc.definition AS default_value
FROM sys.tables t
INNER JOIN sys.columns c
    ON t.object_id = c.object_id
INNER JOIN sys.types ty
    ON c.user_type_id = ty.user_type_id
LEFT JOIN sys.default_constraints dc
    ON c.default_object_id = dc.object_id
WHERE t.name IN (
    'documents',
    'document_sections',
    'document_chunks',
    'ingestion_jobs'
)
ORDER BY t.name, c.column_id;