import React, { useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiDownload, apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading,
} from "../../components/ui/index.jsx";
import MatrixReviewForm from "../../components/matrix/MatrixReviewForm.jsx";

/**
 * Fila de revisão — só mostra entradas com `result IS NULL`. Permite ao
 * especialista expandir e rever inline.
 */
export default function SpecialistQueue() {
  const { token } = useAuth();
  const [expanded, setExpanded] = useState(null);
  const [savingId, setSavingId] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadError, setDownloadError] = useState("");

  const list = useAsyncList(
    () => apiJson("/specialist/traceability?only_pending=true&only_review_requested=true&limit=100", { token }),
    [token]
  );

  const handleReview = async (traceId, payload) => {
    setSavingId(traceId);
    try {
      await apiJson(`/specialist/traceability/${traceId}`, {
        method: "PATCH",
        token,
        body: payload,
      });
      // Após marcar, sai da fila (já não está pending) — refresh
      await list.reload();
      setExpanded(null);
    } finally {
      setSavingId(null);
    }
  };

  const handleDownload = async (entry) => {
    if (!entry?.id) return;

    setDownloadingId(entry.id);
    setDownloadError("");

    try {
      await apiDownload(`/specialist/traceability/${entry.id}/download`, {
        token,
        filename: entry.download_name || "documento_regulatorio.docx",
      });
    } catch (err) {
      setDownloadError(err.message || "Erro ao descarregar documento.");
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <>
      <PageHeader
        crumb="Especialista · Análise"
        title={<>Pedidos de <em>revisão</em></>}
        sub="Entradas que os utilizadores enviaram explicitamente para revisão especializada."
        actions={
          <Button variant="ghost" size="small" onClick={list.reload}>Recarregar</Button>
        }
      />

      {list.loading && <Spinner label="A carregar fila" />}
      {list.error && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {list.error}
        </div>
      )}
      {!list.loading && !list.error && list.items.length === 0 && (
        <EmptyState
          title="Sem pedidos enviados"
          message="Não há pedidos de revisão enviados por utilizadores neste momento."
        />
      )}

      {downloadError && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13, marginBottom: 12 }}>
          {downloadError}
        </div>
      )}

      {list.items.length > 0 && (
        <>
          <SectionHeading>{list.items.length} entrada(s) a aguardar revisão</SectionHeading>
          {list.items.map((e) => {
            const isOpen = expanded === e.id;
            return (
              <article
                key={e.id}
                className="admin-row"
                style={{ cursor: "pointer" }}
                onClick={() => setExpanded(isOpen ? null : e.id)}
              >
                <div>
                  <div className="admin-row__primary">
                    {(e.question || e.regulatory_step || e.download_name || e.trace_type || "—").slice(0, 120)}
                  </div>
                  <div className="admin-row__meta">
                    {e.trace_type} · {(e.created_at || "").slice(0, 16).replace("T", " ")}
                  </div>
                </div>
                <div className="admin-row__pills">
                  <StatusPill tone="warn">Pedido pelo utilizador</StatusPill>
                  <StatusPill tone="muted">Por rever</StatusPill>
                </div>
                {isOpen && (
                  <div className="admin-row__expand" onClick={(ev) => ev.stopPropagation()}>
                    <SectionHeading>Conteúdo</SectionHeading>
                    {e.question && (
                      <div style={{ marginBottom: 10 }}>
                        <Label>Pergunta</Label>
                        <div className="admin-matrix-detail">{e.question}</div>
                      </div>
                    )}
                    {e.answer && (
                      <div style={{ marginBottom: 10 }}>
                        <Label>Resposta</Label>
                        <div className="admin-matrix-detail">{e.answer}</div>
                      </div>
                    )}

                    {canDownloadEntry(e) && (
                      <div style={{ marginBottom: 14 }}>
                        <Label>Documento gerado</Label>
                        <div className="admin-matrix-detail">
                          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                            <span>📎 {e.download_name || "Documento regulatório gerado"}</span>

                            <Button
                              size="small"
                              variant="ghost"
                              disabled={downloadingId === e.id}
                              onClick={() => handleDownload(e)}
                            >
                              {downloadingId === e.id ? "A descarregar..." : "Descarregar documento"}
                            </Button>
                          </div>
                        </div>
                      </div>
                    )}

                    {(e.user_feedback_result || e.user_feedback_notes) && (
                      <div style={{ marginBottom: 14 }}>
                        <Label>Feedback do utilizador</Label>

                        <div className="admin-matrix-detail">
                          {e.user_feedback_result && (
                            <div style={{ marginBottom: 6 }}>
                              Resultado do utilizador: <strong>{e.user_feedback_result}</strong>
                            </div>
                          )}

                          {e.user_feedback_notes && (
                            <div>{e.user_feedback_notes}</div>
                          )}
                        </div>
                      </div>
                    )}

                    <MatrixReviewForm
                      entry={e}
                      onSubmit={handleReview}
                      busy={savingId === e.id}
                    />
                  </div>
                )}
              </article>
            );
          })}
        </>
      )}
    </>
  );
}

function canDownloadEntry(entry) {
  return (
    entry?.trace_type === "regulatory_document" &&
    (entry?.download_name || entry?.regulatory_session_id)
  );
}

function Label({ children }) {
  return (
    <div style={{
      fontFamily: "var(--mono)",
      fontSize: 9.5,
      letterSpacing: "0.16em",
      textTransform: "uppercase",
      color: "var(--ink-faded)",
      marginBottom: 4,
    }}>
      {children}
    </div>
  );
}
