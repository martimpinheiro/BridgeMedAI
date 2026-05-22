import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import "../../components/matrix/matrix.css";
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
import {
  IconCheck,
  IconX,
  IconActivity,
  IconChat,
} from "../../components/ui/Icons.jsx";

/**
 * UserValidation — matriz do utilizador.
 *
 * Objetivo:
 * - mostrar uma pré-validação automática das respostas do chatbot;
 * - cruzar a resposta com casos de referência internos;
 * - permitir ao utilizador dar feedback simples: útil / parcial / não útil;
 * - ajudar a detetar erros antes de enviar para revisão de especialista.
 */
export default function UserValidation() {
  const { token } = useAuth();
  const [savingId, setSavingId] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [noteDraft, setNoteDraft] = useState("");

  const list = useAsyncList(
    () => apiJson("/user/validation?limit=100", { token }),
    [token]
  );

  const stats = useMemo(() => {
    const s = {
      total: list.items.length,
      autoOk: 0,
      autoParcial: 0,
      autoNok: 0,
      noCase: 0,
      feedbackPending: 0,
    };

    for (const e of list.items) {
      const status = e.auto_validation?.status;

      if (status === "OK") s.autoOk++;
      else if (status === "PARCIAL") s.autoParcial++;
      else if (status === "NOK") s.autoNok++;
      else s.noCase++;

      if (!e.user_feedback_result) s.feedbackPending++;
    }

    return s;
  }, [list.items]);

  async function markResult(traceId, result) {
  setSavingId(traceId);

  try {
    await apiJson(`/user/validation/${traceId}/feedback`, {
      method: "PATCH",
      token,
      body: {
        result,
        notes: noteDraft.trim() || null,
      },
    });

    await list.reload();
    setOpenId(null);
    setNoteDraft("");
  } finally {
    setSavingId(null);
  }
}

async function requestReview(traceId) {
  setSavingId(traceId);

  try {
    await apiJson(`/user/validation/${traceId}/request-review`, {
      method: "POST",
      token,
    });

    await list.reload();
  } finally {
    setSavingId(null);
  }
}

  return (
    <>
      <PageHeader
        crumb="Cliente · Qualidade"
        title={
          <>
            Validar <em>respostas</em>
          </>
        }
        sub="Vê uma pré-validação automática das respostas do chatbot e deixa feedback antes de enviar para revisão especializada."
        actions={
          <Button variant="ghost" size="small" onClick={list.reload}>
            Recarregar
          </Button>
        }
      />

      <Grid cols={4} style={{ marginBottom: 24 }}>
        <KPICard
          label="Total"
          value={list.loading ? "…" : stats.total}
          icon={<IconActivity size={16} />}
        />

        <KPICard
          label="Consistentes"
          value={list.loading ? "…" : stats.autoOk}
          deltaDir="up"
          delta={stats.total ? `${Math.round((stats.autoOk / stats.total) * 100)}%` : ""}
          icon={<IconCheck size={16} />}
        />

        <KPICard
          label="Parciais"
          value={list.loading ? "…" : stats.autoParcial}
          icon={<IconActivity size={16} />}
        />

        <KPICard
          label="Possíveis erros"
          value={list.loading ? "…" : stats.autoNok}
          icon={<IconX size={16} />}
        />
      </Grid>

      {list.loading && <Spinner label="A carregar interações" />}

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
        <EmptyState
          title="Sem interações para validar"
          message="Usa o chatbot e depois volta aqui para veres a pré-validação automática das respostas."
          action={
            <Button as={Link} to="/user/chat">
              <IconChat size={14} /> Abrir chatbot
            </Button>
          }
        />
      )}

      {list.items.length > 0 && (
        <>
          <SectionHeading>As tuas interações recentes</SectionHeading>

          {list.items.map((e) => {
            const isOpen = openId === e.id;

            const feedbackTone =
              !e.user_feedback_result
                ? "muted"
                : e.user_feedback_result === "OK"
                  ? "ok"
                  : e.user_feedback_result === "PARCIAL"
                    ? "warn"
                    : "bad";

            const auto = e.auto_validation || {};

            const autoTone =
              auto.status === "OK"
                ? "ok"
                : auto.status === "PARCIAL"
                  ? "warn"
                  : auto.status === "NOK"
                    ? "bad"
                    : "muted";

            return (
              <article
                key={e.id}
                className="admin-row"
                style={{ cursor: "pointer" }}
                onClick={() => {
                  setOpenId(isOpen ? null : e.id);
                  setNoteDraft("");
                }}
              >
                <div>
                  <div className="admin-row__primary">
                    {(e.question || e.regulatory_step || e.download_name || e.trace_type || "—").slice(0, 110)}
                  </div>

                  <div className="admin-row__meta">
                    {e.trace_type} · {(e.created_at || "").slice(0, 16).replace("T", " ")}
                  </div>
                </div>

                <div className="admin-row__pills">
                  <StatusPill tone={autoTone}>
                    {auto.status_label || "Sem pré-validação"}
                  </StatusPill>

                  <StatusPill tone={feedbackTone}>
                    {e.user_feedback_result || "Feedback por dar"}
                  </StatusPill>
                </div>

                {isOpen && (
                  <div
                    className="admin-row__expand"
                    onClick={(ev) => ev.stopPropagation()}
                  >
                    {auto.status && (
                      <div style={{ marginBottom: 14 }}>
                        <Label>Pré-validação automática</Label>

                        <div className="admin-matrix-detail">
                          <div style={{ marginBottom: 8 }}>
                            <strong>{auto.status_label || "Sem pré-validação"}</strong>

                            {auto.case && (
                              <span>
                                {" "}· Caso: {auto.case.title} · Similaridade:{" "}
                                {Math.round((auto.match_score || 0) * 100)}%
                              </span>
                            )}
                          </div>

                          {auto.recommendation && (
                            <div style={{ marginBottom: 10 }}>
                              {auto.recommendation}
                            </div>
                          )}

                          {Array.isArray(auto.checks) && auto.checks.length > 0 && (
                            <div style={{ display: "grid", gap: 8 }}>
                              {auto.checks.map((c) => (
                                <div
                                  key={c.key}
                                  style={{
                                    padding: "8px 10px",
                                    borderRadius: 8,
                                    border: "1px solid rgba(0,0,0,0.08)",
                                    background: c.ok
                                      ? "rgba(42,120,80,0.06)"
                                      : "rgba(162,45,45,0.06)",
                                  }}
                                >
                                  <div style={{ fontWeight: 700, fontSize: 13 }}>
                                    {c.ok ? "✓" : "⚠"} {c.label}
                                  </div>

                                  <div style={{ fontSize: 12, marginTop: 3 }}>
                                    Esperado: {c.expected || "—"}
                                  </div>

                                  <div style={{ fontSize: 12 }}>
                                    Detetado: {c.observed || "—"}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {e.question && (
                      <div style={{ marginBottom: 10 }}>
                        <Label>A tua pergunta</Label>
                        <div className="admin-matrix-detail">
                          {e.question}
                        </div>
                      </div>
                    )}

                    {e.answer && (
                      <div style={{ marginBottom: 14 }}>
                        <Label>Resposta do assistant</Label>
                        <div
                          className="admin-matrix-detail"
                          style={{ maxHeight: 240 }}
                        >
                          {e.answer}
                        </div>
                      </div>
                    )}

                    <div className="matrix-review" style={{ marginTop: 0 }}>
                      <div className="matrix-review__head">
                        <span className="matrix-review__label">
                          A tua avaliação
                        </span>
                      </div>

                      <div className="matrix-review__field">
                        <label className="matrix-review__field-label">
                          Notas (opcional)
                        </label>

                        <textarea
                          className="matrix-review__textarea"
                          rows={3}
                          placeholder="Ex: 'A resposta foi útil mas faltou citar o artigo X' ou 'Não percebi a classificação que sugeriu'"
                          value={noteDraft}
                          onChange={(ev) => setNoteDraft(ev.target.value)}
                          disabled={savingId === e.id}
                        />
                      </div>

                      <div className="matrix-review__actions" style={{ marginTop: 12 }}>
                        <Button
                          size="small"
                          onClick={() => markResult(e.id, "OK")}
                          disabled={savingId === e.id}
                        >
                          <IconCheck size={12} /> Útil
                        </Button>

                        <Button
                          size="small"
                          variant="ghost"
                          onClick={() => markResult(e.id, "PARCIAL")}
                          disabled={savingId === e.id}
                        >
                          Parcialmente útil
                        </Button>

                        <Button
                          size="small"
                          variant="danger"
                          onClick={() => markResult(e.id, "NOK")}
                          disabled={savingId === e.id}
                        >
                          <IconX size={12} /> Não foi útil
                        </Button>

                        <Button
                          size="small"
                          variant="ghost"
                          onClick={() => requestReview(e.id)}
                          disabled={savingId === e.id || e.review_requested}
                        >
                          {e.review_requested ? "Enviado para especialista" : "Enviar para especialista"}
                        </Button>


                      </div>
                    </div>
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