import React, { useMemo, useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiDownload, apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import {
  PageHeader,
  Button,
  StatusPill,
  Spinner,
  EmptyState,
  SectionHeading,
  KPICard,
  Grid,
} from "../../components/ui/index.jsx";
import MatrixReviewForm from "../../components/matrix/MatrixReviewForm.jsx";
import { IconScroll, IconAlert, IconCheck } from "../../components/ui/Icons.jsx";

const TRACE_TYPES = [
  { value: "", label: "Todos os tipos" },
  { value: "chat", label: "Chat (RAG)" },
  { value: "regulatory_analysis", label: "Análise regulatória" },
  { value: "regulatory_document", label: "Geração de documento" },
];

const RESULTS = [
  { value: "", label: "Qualquer resultado" },
  { value: "OK", label: "OK" },
  { value: "PARCIAL", label: "Parcial" },
  { value: "NOK", label: "NOK" },
];

const SEVERITIES = [
  { value: "", label: "Qualquer severidade" },
  { value: "baixa", label: "Baixa" },
  { value: "média", label: "Média" },
  { value: "alta", label: "Alta" },
];

export default function SpecialistMatrix() {
  const { token } = useAuth();

  const [traceType, setTraceType] = useState("");
  const [result, setResult] = useState("");
  const [severity, setSeverity] = useState("");
  const [onlyPending, setOnlyPending] = useState(false);
  const [onlyReviewRequested, setOnlyReviewRequested] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [savingId, setSavingId] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);
  const [downloadError, setDownloadError] = useState("");

  const list = useAsyncList(() => {
    const params = new URLSearchParams();

    params.set("limit", "200");

    if (traceType) params.set("trace_type", traceType);
    if (result && !onlyPending) params.set("result", result);
    if (severity) params.set("severity", severity);
    if (onlyPending) params.set("only_pending", "true");
    if (onlyReviewRequested) params.set("only_review_requested", "true");

    return apiJson(`/specialist/traceability?${params.toString()}`, { token });
  }, [token, traceType, result, severity, onlyPending, onlyReviewRequested]);

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

  const stats = useMemo(() => {
    const s = {
      total: list.items.length,
      ok: 0,
      parcial: 0,
      nok: 0,
      pending: 0,
      alta: 0,
      reviewRequested: 0,
    };

    for (const e of list.items) {
      if (!e.result) s.pending++;
      else if (e.result === "OK") s.ok++;
      else if (e.result === "PARCIAL") s.parcial++;
      else if (e.result === "NOK") s.nok++;

      if (e.severity === "alta") s.alta++;
      if (e.review_requested) s.reviewRequested++;
    }

    return s;
  }, [list.items]);

  return (
    <>
      <PageHeader
        crumb="Especialista · Análise"
        title={
          <>
            Matriz <em>regulatória</em>
          </>
        }
        sub="Vista global da rastreabilidade. Filtra, expande para ver detalhe e marca a revisão."
        actions={
          <Button variant="ghost" size="small" onClick={list.reload}>
            Recarregar
          </Button>
        }
      />

      <Grid cols={4} style={{ marginBottom: 24 }}>
        <KPICard
          label="Entradas (top 200)"
          value={list.loading ? "…" : stats.total}
          icon={<IconScroll size={16} />}
        />

        <KPICard
          label="Por rever"
          value={list.loading ? "…" : stats.pending}
          deltaDir={stats.pending > 0 ? "down" : "up"}
          delta={stats.pending > 0 ? "ação requerida" : "tudo revisto"}
          icon={<IconAlert size={16} />}
        />

        <KPICard
          label="Pedidos enviados"
          value={list.loading ? "…" : stats.reviewRequested}
          icon={<IconAlert size={16} />}
        />

        <KPICard
          label="OK"
          value={list.loading ? "…" : stats.ok}
          deltaDir="up"
          delta={stats.total ? `${Math.round((stats.ok / stats.total) * 100)}% do total` : ""}
          icon={<IconCheck size={16} />}
        />
      </Grid>

      <div className="admin-filterbar">
        <span className="admin-filterbar__label">Filtrar</span>

        <select value={traceType} onChange={(e) => setTraceType(e.target.value)}>
          {TRACE_TYPES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <select
          value={result}
          onChange={(e) => setResult(e.target.value)}
          disabled={onlyPending}
        >
          {RESULTS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {SEVERITIES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 13,
            color: "var(--ink-muted)",
            cursor: "pointer",
          }}
        >
          <input
            type="checkbox"
            checked={onlyPending}
            onChange={(e) => setOnlyPending(e.target.checked)}
            style={{ accentColor: "var(--forest)" }}
          />
          Só por rever
        </label>

        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 13,
            color: "var(--ink-muted)",
            cursor: "pointer",
          }}
        >
          <input
            type="checkbox"
            checked={onlyReviewRequested}
            onChange={(e) => setOnlyReviewRequested(e.target.checked)}
            style={{ accentColor: "var(--forest)" }}
          />
          Só pedidos enviados
        </label>
      </div>

      {list.loading && <Spinner label="A carregar matriz" />}

      {list.error && (
        <div
          style={{
            padding: "12px 14px",
            background: "rgba(162,45,45,0.06)",
            borderLeft: "3px solid var(--missing)",
            borderRadius: 4,
            color: "var(--missing)",
            fontSize: 13,
          }}
        >
          {list.error}
        </div>
      )}

      {!list.loading && !list.error && list.items.length === 0 && (
        <EmptyState title="Sem entradas" message="Nada na matriz com estes filtros." />
      )}

      {downloadError && (
        <div
          style={{
            padding: "12px 14px",
            background: "rgba(162,45,45,0.06)",
            borderLeft: "3px solid var(--missing)",
            borderRadius: 4,
            color: "var(--missing)",
            fontSize: 13,
            marginBottom: 12,
          }}
        >
          {downloadError}
        </div>
      )}

      {list.items.length > 0 && (
        <>
          <SectionHeading>{list.items.length} entrada(s)</SectionHeading>

          {list.items.map((e) => {
            const isOpen = expanded === e.id;

            const tone = !e.result
              ? "muted"
              : e.result === "OK"
                ? "ok"
                : e.result === "PARCIAL"
                  ? "warn"
                  : "bad";

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
                  {e.review_requested && (
                    <StatusPill tone="warn">Pedido pelo utilizador</StatusPill>
                  )}

                  <StatusPill tone={tone}>{e.result || "Por rever"}</StatusPill>

                  {e.severity && (
                    <StatusPill
                      tone={
                        e.severity === "alta"
                          ? "bad"
                          : e.severity === "média"
                            ? "warn"
                            : "muted"
                      }
                    >
                      {e.severity}
                    </StatusPill>
                  )}

                  {e.error_type && <StatusPill tone="info">{e.error_type}</StatusPill>}
                </div>

                {isOpen && (
                  <div
                    className="admin-row__expand"
                    onClick={(ev) => ev.stopPropagation()}
                  >
                    <SectionHeading>Detalhe</SectionHeading>

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

                    {e.intent && (
                      <div style={{ marginBottom: 10 }}>
                        <Label>Intent</Label>
                        <code
                          style={{
                            fontFamily: "var(--mono)",
                            fontSize: 12,
                            color: "var(--forest)",
                          }}
                        >
                          {e.intent}
                        </code>
                      </div>
                    )}

                    {(e.user_feedback_result || e.user_feedback_notes) && (
                      <div style={{ marginBottom: 14 }}>
                        <Label>Feedback do utilizador</Label>

                        <div className="admin-matrix-detail">
                          {e.user_feedback_result && (
                            <div style={{ marginBottom: 6 }}>
                              Resultado do utilizador:{" "}
                              <strong>{e.user_feedback_result}</strong>
                            </div>
                          )}

                          {e.user_feedback_notes && <div>{e.user_feedback_notes}</div>}
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
    <div
      style={{
        fontFamily: "var(--mono)",
        fontSize: 9.5,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: "var(--ink-faded)",
        marginBottom: 4,
      }}
    >
      {children}
    </div>
  );
}