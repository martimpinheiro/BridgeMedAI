import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading,
} from "../../components/ui/index.jsx";
import { IconChat, IconScroll, IconActivity, IconArrowRight } from "../../components/ui/Icons.jsx";

const TYPE_LABEL = {
  chat: "Conversa",
  regulatory_analysis: "Análise regulatória",
  regulatory_document: "Documento gerado",
};

const TYPE_ICON = {
  chat: <IconChat size={14} />,
  regulatory_analysis: <IconActivity size={14} />,
  regulatory_document: <IconScroll size={14} />,
};

export default function UserHistory() {
  const { token } = useAuth();
  const [typeFilter, setTypeFilter] = useState("");
  const [expanded, setExpanded] = useState(null);

  const list = useAsyncList(
    () => apiJson("/traceability?limit=200", { token }),
    [token]
  );

  const filtered = useMemo(() => {
    if (!typeFilter) return list.items;
    return list.items.filter((e) => e.trace_type === typeFilter);
  }, [list.items, typeFilter]);

  // Agrupar por dia
  const grouped = useMemo(() => {
    const map = {};
    for (const e of filtered) {
      const day = (e.created_at || "").slice(0, 10);
      if (!map[day]) map[day] = [];
      map[day].push(e);
    }
    return map;
  }, [filtered]);

  const stats = useMemo(() => {
    const s = { chat: 0, regulatory_analysis: 0, regulatory_document: 0 };
    for (const e of list.items) s[e.trace_type] = (s[e.trace_type] || 0) + 1;
    return s;
  }, [list.items]);

  return (
    <>
      <PageHeader
        crumb="Cliente · Pessoal"
        title={<>O meu <em>histórico</em></>}
        sub={`${list.items.length} interação(ões) no total · ${stats.chat} conversas · ${stats.regulatory_document} documentos gerados`}
        actions={
          <Button variant="ghost" size="small" onClick={list.reload}>
            Recarregar
          </Button>
        }
      />

      <div className="admin-filterbar">
        <span className="admin-filterbar__label">Filtrar</span>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">Todos os tipos</option>
          <option value="chat">Conversas ({stats.chat})</option>
          <option value="regulatory_analysis">Análises regulatórias ({stats.regulatory_analysis})</option>
          <option value="regulatory_document">Documentos gerados ({stats.regulatory_document})</option>
        </select>
        <Button as={Link} to="/user/chat" size="small" variant="ghost">
          <IconChat size={12} /> Abrir chatbot
        </Button>
      </div>

      {list.loading && <Spinner label="A carregar histórico" />}
      {list.error && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {list.error}
        </div>
      )}
      {!list.loading && !list.error && filtered.length === 0 && (
        <EmptyState
          title={typeFilter ? "Sem entradas deste tipo" : "Sem histórico ainda"}
          message="Quando começares a usar o chatbot, as tuas interações aparecem aqui."
          action={
            <Button as={Link} to="/user/chat">
              <IconChat size={14} /> Começar agora
            </Button>
          }
        />
      )}

      {filtered.length > 0 && (
        <>
          {Object.entries(grouped)
            .sort((a, b) => b[0].localeCompare(a[0]))
            .map(([day, entries]) => (
              <div key={day} style={{ marginBottom: 28 }}>
                <SectionHeading>{formatDay(day)} · {entries.length} interação(ões)</SectionHeading>
                {entries.map((e) => {
                  const isOpen = expanded === e.id;
                  return (
                    <article
                      key={e.id}
                      className="admin-row"
                      style={{ cursor: "pointer" }}
                      onClick={() => setExpanded(isOpen ? null : e.id)}
                    >
                      <div>
                        <div className="admin-row__primary" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ color: "var(--forest)" }}>{TYPE_ICON[e.trace_type]}</span>
                          {(e.question || e.regulatory_step || e.download_name || TYPE_LABEL[e.trace_type] || "—").slice(0, 110)}
                        </div>
                        <div className="admin-row__meta">
                          {TYPE_LABEL[e.trace_type] || e.trace_type} · {(e.created_at || "").slice(11, 16)}
                        </div>
                      </div>
                      <div className="admin-row__pills">
                        {e.result && (
                          <StatusPill tone={e.result === "OK" ? "ok" : e.result === "PARCIAL" ? "warn" : "bad"}>
                            {e.result}
                          </StatusPill>
                        )}
                        {!e.result && <StatusPill tone="muted">Não revisto</StatusPill>}
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
                            <div style={{ marginBottom: 10 }}>
                              <Label>Resposta do assistant</Label>
                              <div className="admin-matrix-detail" style={{ maxHeight: 280 }}>{e.answer}</div>
                            </div>
                          )}
                          {e.download_name && (
                            <div style={{ marginBottom: 10 }}>
                              <Label>Documento gerado</Label>
                              <div style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--forest-deep)" }}>
                                📎 {e.download_name}
                              </div>
                            </div>
                          )}
                          {e.intent && (
                            <div style={{ marginBottom: 10 }}>
                              <Label>Tipo de pergunta detetado</Label>
                              <code style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--forest)" }}>{e.intent}</code>
                            </div>
                          )}
                          <Button as={Link} to="/user/validation" size="small" variant="ghost">
                            Validar esta resposta <IconArrowRight size={11} />
                          </Button>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            ))}
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

function formatDay(iso) {
  if (!iso) return "Sem data";
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (iso === today) return "Hoje";
  if (iso === yesterday) return "Ontem";
  try {
    return new Date(iso).toLocaleDateString("pt-PT", {
      weekday: "long", year: "numeric", month: "long", day: "numeric",
    });
  } catch {
    return iso;
  }
}
