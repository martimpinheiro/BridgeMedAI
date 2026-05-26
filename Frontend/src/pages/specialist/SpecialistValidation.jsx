import React, { useEffect, useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading,
} from "../../components/ui/index.jsx";
import MatrixReviewForm from "../../components/matrix/MatrixReviewForm.jsx";
import { IconArrowRight } from "../../components/ui/Icons.jsx";

/**
 * Validação — workflow one-at-a-time. O especialista vê uma entrada por
 * vez, com a próxima a aguardar. Foco máximo, sem distrações.
 */
export default function SpecialistValidation() {
  const { token } = useAuth();
  const [savingId, setSavingId] = useState(null);
  const [currentIdx, setCurrentIdx] = useState(0);

  const list = useAsyncList(
    () => apiJson("/specialist/traceability?only_pending=true&only_review_requested=true&limit=50", { token }),
    [token]
  );

  // Quando a lista muda (após revisão), reposiciona em 0
  useEffect(() => {
    setCurrentIdx(0);
  }, [list.items.length]);

  const handleReview = async (traceId, payload) => {
    setSavingId(traceId);
    try {
      await apiJson(`/specialist/traceability/${traceId}`, {
        method: "PATCH",
        token,
        body: payload,
      });
      await list.reload();
    } finally {
      setSavingId(null);
    }
  };

  const handleSkip = () => {
    setCurrentIdx((i) => Math.min(i + 1, list.items.length - 1));
  };

  if (list.loading) {
    return (
      <>
        <PageHeader
          crumb="Especialista · Análise"
          title={<>Validação <em>item-a-item</em></>}
          sub="Revê, um a um, os pedidos enviados pelos utilizadores."
          actions={
            <Button variant="ghost" size="small" onClick={list.reload}>Recarregar fila</Button>
          }
        />
        <Spinner label="A carregar fila" />
      </>
    );
  }

  if (list.error) {
    return (
      <>
        <PageHeader
          crumb="Especialista · Análise"
          title={<>Validação <em>item-a-item</em></>}
        />
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {list.error}
        </div>
      </>
    );
  }

  if (list.items.length === 0) {
    return (
      <>
        <PageHeader
          crumb="Especialista · Análise"
          title={<>Validação <em>item-a-item</em></>}
        />
        <EmptyState
          title="Tudo revisto"
          message="A fila está vazia. Bom trabalho — vai descansar."
        />
      </>
    );
  }

  const entry = list.items[currentIdx] || list.items[0];
  const total = list.items.length;
  const position = currentIdx + 1;

  return (
    <>
      <PageHeader
        crumb="Especialista · Análise"
        title={<>Validação <em>item-a-item</em></>}
        sub="Vê uma entrada de cada vez. Marca o resultado e a próxima aparece automaticamente."
        actions={
          <Button variant="ghost" size="small" onClick={list.reload}>Recarregar fila</Button>
        }
      />

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{
          fontFamily: "var(--mono)",
          fontSize: 11,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "var(--ink-faded)",
        }}>
          Item {position} de {total}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Button
            variant="ghost"
            size="small"
            disabled={currentIdx >= total - 1}
            onClick={handleSkip}
          >
            Saltar para o próximo <IconArrowRight size={11} />
          </Button>
        </div>
      </div>

      <Card>
        <div style={{ marginBottom: 14 }}>
          <Label>Tipo</Label>
          <div style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            marginTop: 4,
          }}>
            <StatusPill tone="forest">{entry.trace_type}</StatusPill>
            <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-faded)" }}>
              {(entry.created_at || "").slice(0, 16).replace("T", " ")}
            </span>
          </div>
        </div>

        {entry.question && (
          <div style={{ marginBottom: 14 }}>
            <Label>Pergunta do utilizador</Label>
            <div className="admin-matrix-detail" style={{ maxHeight: 180 }}>
              {entry.question}
            </div>
          </div>
        )}

        {entry.answer && (
          <div style={{ marginBottom: 14 }}>
            <Label>Resposta do assistant</Label>
            <div className="admin-matrix-detail" style={{ maxHeight: 360 }}>
              {entry.answer}
            </div>
          </div>
        )}

        {entry.intent && (
          <div style={{ marginBottom: 14 }}>
            <Label>Intent inferida</Label>
            <code style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--forest)" }}>
              {entry.intent}
            </code>
          </div>
        )}

        {(entry.user_feedback_result || entry.user_feedback_notes) && (
          <div style={{ marginBottom: 14 }}>
            <Label>Feedback do utilizador</Label>

            <div className="admin-matrix-detail">
              {entry.user_feedback_result && (
                <div style={{ marginBottom: 6 }}>
                  Resultado do utilizador: <strong>{entry.user_feedback_result}</strong>
                </div>
              )}

              {entry.user_feedback_notes && (
                <div>{entry.user_feedback_notes}</div>
              )}
            </div>
          </div>
        )}

        <MatrixReviewForm
          entry={entry}
          onSubmit={handleReview}
          busy={savingId === entry.id}
        />
      </Card>
    </>
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
