USE BridgeMedAI;
GO


SELECT
    d.short_name,
    s.section_type,
    s.section_number,
    s.section_title,
    c.chunk_index,
    LEFT(c.chunk_text, 150) AS chunk_preview,
    c.citation_label
FROM dbo.documents d
INNER JOIN dbo.document_sections s
    ON s.document_id = d.id
INNER JOIN dbo.document_chunks c
    ON c.section_id = s.id
ORDER BY d.id, s.id, c.chunk_index;