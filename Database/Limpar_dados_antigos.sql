USE [BridgeMedAI];
GO

DELETE FROM dbo.ingestion_jobs
WHERE document_id IN (
    SELECT id FROM dbo.documents WHERE short_name IN ('MDR', 'AI_ACT')
);

DELETE FROM dbo.document_chunks
WHERE document_id IN (
    SELECT id FROM dbo.documents WHERE short_name IN ('MDR', 'AI_ACT')
);

DELETE FROM dbo.document_sections
WHERE document_id IN (
    SELECT id FROM dbo.documents WHERE short_name IN ('MDR', 'AI_ACT')
);

DELETE FROM dbo.documents
WHERE short_name IN ('MDR', 'AI_ACT');
GO