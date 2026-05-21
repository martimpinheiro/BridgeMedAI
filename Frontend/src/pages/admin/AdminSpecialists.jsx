import React, { useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiDownload, apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "./admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading,
} from "../../components/ui/index.jsx";
import { IconCheck, IconX, IconShield } from "../../components/ui/Icons.jsx";

const ROLE_LABEL = {
  user: "Utilizador",
  specialist: "Especialista",
  admin: "Admin",
};

export default function AdminSpecialists() {
  const { token } = useAuth();
  const [tab, setTab] = useState("pending");

  const pending = useAsyncList(
    () => apiJson("/admin/specialist-queue", { token }),
    [token]
  );
  const all = useAsyncList(
    () => apiJson("/admin/users?role=specialist", { token }),
    [token, tab]
  );

  const counts = {
    pending: pending.items.length,
    all: all.items.length,
  };

  return (
    <>
      <PageHeader
        crumb="Administração · Pessoas"
        title={<>Gestão de <em>especialistas</em></>}
        sub="Aprovar ou rejeitar candidaturas, ver perfis e credenciais."
        actions={
          <Button variant="ghost" size="small" onClick={() => { pending.reload(); all.reload(); }}>
            Recarregar
          </Button>
        }
      />

      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid rgba(21,42,32,0.1)", marginBottom: 22 }}>
        <TabButton active={tab === "pending"} onClick={() => setTab("pending")}>
          Candidaturas pendentes {counts.pending > 0 && <span style={badgeStyle}>{counts.pending}</span>}
        </TabButton>
        <TabButton active={tab === "all"} onClick={() => setTab("all")}>
          Todos os especialistas
        </TabButton>
      </div>

      {tab === "pending" && <PendingQueue list={pending} token={token} onChanged={() => { pending.reload(); all.reload(); }} />}
      {tab === "all" && <AllSpecialists list={all} />}
    </>
  );
}

/* ----------------- Sub-views ----------------- */
function PendingQueue({ list, token, onChanged }) {
  const [actionError, setActionError] = useState("");
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");

  async function approve(id) {
    setActionError("");
    try {
      await apiJson(`/admin/specialists/${id}/approve`, { method: "POST", token });
      onChanged();
    } catch (err) { setActionError(err.message || "Erro ao aprovar."); }
  }

  async function reject(id) {
    if (!reason.trim()) { setActionError("Indica um motivo."); return; }
    setActionError("");
    try {
      await apiJson(`/admin/specialists/${id}/reject`, {
        method: "POST", token, body: { reason: reason.trim() },
      });
      setRejecting(null); setReason(""); onChanged();
    } catch (err) { setActionError(err.message || "Erro ao rejeitar."); }
  }

  async function download(credId, name) {
    try { await apiDownload(`/admin/credentials/${credId}/download`, { token, filename: name }); }
    catch (err) { setActionError(err.message || "Erro a descarregar."); }
  }

  if (list.loading) return <Spinner label="A carregar candidaturas" />;
  if (list.error) return <ErrorBanner message={list.error} />;
  if (list.items.length === 0) {
    return (
      <EmptyState
        title="Sem candidaturas pendentes"
        message="Quando houver novos pedidos de especialista vão aparecer aqui."
      />
    );
  }

  return (
    <>
      {actionError && <ErrorBanner message={actionError} />}
      <SectionHeading>{list.items.length} candidatura(s) a aguardar revisão</SectionHeading>
      {list.items.map((item) => (
        <article key={item.id} className="admin-row">
          <div>
            <div className="admin-row__primary">{item.full_name}</div>
            <div className="admin-row__secondary">{item.email}</div>
            <div className="admin-row__meta">
              {[item.specialty, item.institution, item.country].filter(Boolean).join(" · ") || "Sem detalhes adicionais"}
            </div>
          </div>
          <div className="admin-row__pills">
            <StatusPill tone="warn">Pending</StatusPill>
          </div>

          {item.credentials?.length > 0 && (
            <div className="admin-row__expand">
              <SectionHeading>Credenciais submetidas</SectionHeading>
              {item.credentials.map((c) => (
                <div key={c.id} className="admin-cred">
                  <span>{c.original_filename}</span>
                  <Button size="small" variant="ghost" onClick={() => download(c.id, c.original_filename)}>
                    Descarregar
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="admin-row__expand" style={{ borderTop: "none", paddingTop: 0, marginTop: 8 }}>
            {rejecting === item.id ? (
              <>
                <textarea
                  className="admin-reason"
                  placeholder="Motivo da rejeição (obrigatório)"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  autoFocus
                />
                <div className="admin-actions">
                  <Button variant="danger" size="small" onClick={() => reject(item.id)}>
                    <IconX size={12} /> Confirmar rejeição
                  </Button>
                  <Button variant="ghost" size="small" onClick={() => { setRejecting(null); setReason(""); }}>
                    Cancelar
                  </Button>
                </div>
              </>
            ) : (
              <div className="admin-actions">
                <Button size="small" onClick={() => approve(item.id)}>
                  <IconCheck size={12} /> Aprovar
                </Button>
                <Button variant="danger" size="small" onClick={() => { setRejecting(item.id); setReason(""); }}>
                  <IconX size={12} /> Rejeitar
                </Button>
              </div>
            )}
          </div>
        </article>
      ))}
    </>
  );
}

function AllSpecialists({ list }) {
  if (list.loading) return <Spinner label="A carregar especialistas" />;
  if (list.error) return <ErrorBanner message={list.error} />;
  if (list.items.length === 0) {
    return (
      <EmptyState
        title="Sem especialistas registados"
        message="Quando aprovares uma candidatura, o especialista aparece aqui."
      />
    );
  }
  return (
    <>
      <SectionHeading>{list.items.length} especialista(s) no sistema</SectionHeading>
      {list.items.map((u) => (
        <article key={u.id} className="admin-row">
          <div>
            <div className="admin-row__primary">
              <IconShield size={14} style={{ verticalAlign: "middle", marginRight: 6, color: "var(--forest)" }} />
              {u.full_name}
            </div>
            <div className="admin-row__secondary">{u.email}</div>
            <div className="admin-row__meta">{ROLE_LABEL[u.role] || u.role}</div>
          </div>
          <div className="admin-row__pills">
            <StatusPill tone={u.status === "active" ? "ok" : u.status === "pending" ? "warn" : u.status === "rejected" ? "bad" : "muted"}>
              {u.status}
            </StatusPill>
          </div>
        </article>
      ))}
    </>
  );
}

/* ----------------- helpers ----------------- */
function TabButton({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        appearance: "none",
        background: "transparent",
        border: "none",
        padding: "10px 16px 12px",
        fontFamily: "var(--mono)",
        fontSize: 10.5,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: active ? "var(--forest-deep)" : "var(--ink-faded)",
        borderBottom: active ? "1.5px solid var(--forest-deep)" : "1.5px solid transparent",
        marginBottom: -1,
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      {children}
    </button>
  );
}

const badgeStyle = {
  background: "var(--forest)",
  color: "var(--cream)",
  borderRadius: 999,
  padding: "1px 7px",
  fontSize: 10,
};

function ErrorBanner({ message }) {
  return (
    <div style={{
      padding: "12px 14px",
      background: "rgba(162,45,45,0.06)",
      borderLeft: "3px solid var(--missing)",
      borderRadius: 4,
      color: "var(--missing)",
      fontFamily: "var(--body)",
      fontSize: 13,
      marginBottom: 14,
    }}>
      {message}
    </div>
  );
}
