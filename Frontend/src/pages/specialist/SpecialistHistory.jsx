import React, { useMemo } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading,
} from "../../components/ui/index.jsx";

/**
 * Histórico do especialista — só mostra entradas que ELE reviu (procura
 * o tag [reviewer:<id-prefix>] que adicionamos em update_traceability_review_admin).
 *
 * O backend não tem filtro nativo por reviewer (o schema não tem coluna);
 * fazemos o filtro client-side por simplicidade.
 */
export default function SpecialistHistory() {
  const { token, user } = useAuth();
  const reviewerTag = `[reviewer:${(user?.id || "").slice(0, 8)}]`;

  const list = useAsyncList(
    () => apiJson("/specialist/traceability?limit=500", { token }),
    [token]
  );

  const reviewed = useMemo(
    () => list.items.filter((e) => (e.reviewer_notes || "").includes(reviewerTag)),
    [list.items, reviewerTag]
  );

  return (
    <>
      <PageHeader
        crumb="Especialista · Pessoal"
        title={<>O meu <em>histórico</em></>}
        sub="Todas as entradas que tu reviste. Identificadas pelo tag de reviewer nas notas."
        actions={<Button variant="ghost" size="small" onClick={list.reload}>Recarregar</Button>}
      />

      {list.loading && <Spinner label="A carregar histórico" />}
      {list.error && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {list.error}
        </div>
      )}

      {!list.loading && !list.error && reviewed.length === 0 && (
        <EmptyState
          title="Ainda sem histórico"
          message="Quando reveres entradas na fila ou na matriz, vão aparecer aqui."
        />
      )}

      {reviewed.length > 0 && (
        <>
          <SectionHeading>{reviewed.length} revisão(ões) feitas por ti</SectionHeading>
          {reviewed.slice(0, 100).map((e) => (
            <article key={e.id} className="admin-row">
              <div>
                <div className="admin-row__primary">
                  {(e.question || e.regulatory_step || e.trace_type || "—").slice(0, 120)}
                </div>
                <div className="admin-row__meta">
                  {e.trace_type} · revisto {(e.updated_at || "").slice(0, 16).replace("T", " ")}
                </div>
                {e.reviewer_notes && (
                  <div style={{
                    marginTop: 8,
                    fontFamily: "var(--display)",
                    fontStyle: "italic",
                    fontSize: 13,
                    color: "var(--ink-muted)",
                    paddingLeft: 12,
                    borderLeft: "2px solid var(--sage-deep)",
                  }}>
                    “{(e.reviewer_notes || "").replace(/^\[reviewer:[a-f0-9]+\]\s*/i, "") || "(sem notas)"}”
                  </div>
                )}
              </div>
              <div className="admin-row__pills">
                <StatusPill tone={e.result === "OK" ? "ok" : e.result === "PARCIAL" ? "warn" : e.result === "NOK" ? "bad" : "muted"}>
                  {e.result || "—"}
                </StatusPill>
                {e.severity && <StatusPill tone={e.severity === "alta" ? "bad" : e.severity === "média" ? "warn" : "muted"}>{e.severity}</StatusPill>}
                {e.error_type && <StatusPill tone="info">{e.error_type}</StatusPill>}
              </div>
            </article>
          ))}
        </>
      )}
    </>
  );
}
