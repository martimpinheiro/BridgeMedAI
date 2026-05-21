import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import "../../components/matrix/matrix.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading, KPICard, Grid,
} from "../../components/ui/index.jsx";
import {
  IconCheck, IconX, IconActivity, IconArrowRight, IconChat,
} from "../../components/ui/Icons.jsx";

/**
 * UserValidation — versão simplificada da matriz para clientes.
 *
 * O cliente pode marcar AS SUAS PRÓPRIAS interações como "útil/parcial/errado"
 * e deixar uma nota curta para o nosso lado melhorar. Usa o endpoint PATCH
 * /traceability/{id} que filtra por user_id.
 *
 * UI mais simples que admin/specialist:
 *  - Só 3 buttons (✓ útil / ~ parcial / ✗ errado)
 *  - Textarea curta opcional
 *  - Sem severidade nem tipo de erro (o admin/specialist tratam disso depois)
 */
export default function UserValidation() {
  const { token } = useAuth();
  const [savingId, setSavingId] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [noteDraft, setNoteDraft] = useState("");

  const list = useAsyncList(
    () => apiJson("/traceability?limit=100", { token }),
    [token]
  );

  const stats = useMemo(() => {
    const s = { total: list.items.length, ok: 0, parcial: 0, nok: 0, pending: 0 };
    for (const e of list.items) {
      if (!e.result) s.pending++;
      else if (e.result === "OK") s.ok++;
      else if (e.result === "PARCIAL") s.parcial++;
      else if (e.result === "NOK") s.nok++;
    }
    return s;
  }, [list.items]);

  async function markResult(traceId, result) {
    setSavingId(traceId);
    try {
      await apiJson(`/traceability/${traceId}`, {
        method: "PATCH",
        token,
        body: {
          result,
          reviewer_notes: noteDraft.trim() || null,
          severity: null,
          error_type: null,
        },
      });
      await list.reload();
      setOpenId(null);
      setNoteDraft("");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <>
      <PageHeader
        crumb="Cliente · Qualidade"
        title={<>Validar <em>respostas</em></>}
        sub="Diz-nos se as respostas que receberam foram úteis. Isto ajuda-nos a melhorar o copiloto regulatório."
        actions={
          <Button variant="ghost" size="small" onClick={list.reload}>
            Recarregar
          </Button>
        }
      />

      <Grid cols={4} style={{ marginBottom: 24 }}>
        <KPICard label="Total" value={list.loading ? "…" : stats.total} icon={<IconActivity size={16} />} />
        <KPICard
          label="Úteis"
          value={list.loading ? "…" : stats.ok}
          deltaDir="up"
          delta={stats.total ? `${Math.round((stats.ok / stats.total) * 100)}%` : ""}
          icon={<IconCheck size={16} />}
        />
        <KPICard label="Parciais" value={list.loading ? "…" : stats.parcial} icon={<IconActivity size={16} />} />
        <KPICard label="Por validar" value={list.loading ? "…" : stats.pending} icon={<IconActivity size={16} />} />
      </Grid>

      {list.loading && <Spinner label="A carregar interações" />}
      {list.error && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {list.error}
        </div>
      )}
      {!list.loading && !list.error && list.items.length === 0 && (
        <EmptyState
          title="Sem interações para validar"
          message="Usa o chatbot e depois volta aqui para nos dizer se as respostas foram úteis."
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
            const tone = !e.result ? "muted" : e.result === "OK" ? "ok" : e.result === "PARCIAL" ? "warn" : "bad";
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
                  <StatusPill tone={tone}>{e.result || "Por validar"}</StatusPill>
                </div>

                {isOpen && (
                  <div className="admin-row__expand" onClick={(ev) => ev.stopPropagation()}>
                    {e.question && (
                      <div style={{ marginBottom: 10 }}>
                        <Label>A tua pergunta</Label>
                        <div className="admin-matrix-detail">{e.question}</div>
                      </div>
                    )}
                    {e.answer && (
                      <div style={{ marginBottom: 14 }}>
                        <Label>Resposta do assistant</Label>
                        <div className="admin-matrix-detail" style={{ maxHeight: 240 }}>{e.answer}</div>
                      </div>
                    )}

                    <div className="matrix-review" style={{ marginTop: 0 }}>
                      <div className="matrix-review__head">
                        <span className="matrix-review__label">A tua avaliação</span>
                      </div>

                      <div className="matrix-review__field">
                        <label className="matrix-review__field-label">Notas (opcional)</label>
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
