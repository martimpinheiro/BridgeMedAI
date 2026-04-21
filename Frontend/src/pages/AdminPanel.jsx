import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiDownload, apiJson } from "../auth/api.js";

const css = {
  page: {
    minHeight: "100vh",
    background: "var(--cream)",
    fontFamily: "var(--body)",
    color: "var(--ink)",
    padding: "32px 32px 60px",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 24,
    flexWrap: "wrap",
    gap: 12,
  },
  title: {
    margin: 0,
    fontFamily: "var(--display)",
    fontSize: 28,
    fontWeight: 500,
    letterSpacing: -0.2,
  },
  tabs: {
    display: "flex",
    gap: 4,
    borderBottom: "1px solid var(--cream-edge)",
    marginBottom: 20,
  },
  tab: (active) => ({
    padding: "10px 16px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    background: "transparent",
    color: active ? "var(--forest)" : "var(--ink-muted)",
    cursor: "pointer",
    borderBottom: active ? "2px solid var(--forest)" : "2px solid transparent",
    marginBottom: -1,
  }),
  card: {
    background: "var(--paper)",
    border: "1px solid var(--cream-edge)",
    borderRadius: 12,
    boxShadow: "var(--shadow-soft)",
    padding: 18,
    marginBottom: 14,
  },
  row: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    flexWrap: "wrap",
  },
  badge: (tone) => ({
    display: "inline-block",
    padding: "3px 10px",
    borderRadius: 999,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    background:
      tone === "active" ? "rgba(46,125,50,0.12)" :
      tone === "pending" ? "rgba(181,140,62,0.15)" :
      tone === "rejected" ? "rgba(196,85,85,0.12)" :
      "rgba(0,0,0,0.06)",
    color:
      tone === "active" ? "#2e7d32" :
      tone === "pending" ? "#8a6726" :
      tone === "rejected" ? "#8b2e2e" :
      "var(--ink-muted)",
  }),
  btn: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 10,
    border: "1px solid var(--cream-edge)",
    background: "var(--paper)",
    color: "var(--ink)",
    cursor: "pointer",
  },
  btnPrimary: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 10,
    border: "none",
    background: "var(--forest)",
    color: "var(--paper)",
    cursor: "pointer",
  },
  btnDanger: {
    padding: "8px 14px",
    fontSize: 13,
    fontWeight: 600,
    borderRadius: 10,
    border: "1px solid rgba(196,85,85,0.35)",
    background: "transparent",
    color: "#8b2e2e",
    cursor: "pointer",
  },
  textarea: {
    width: "100%",
    boxSizing: "border-box",
    padding: 10,
    fontSize: 13,
    fontFamily: "var(--body)",
    border: "1px solid var(--cream-edge)",
    borderRadius: 8,
    minHeight: 80,
    resize: "vertical",
  },
  input: {
    padding: "8px 10px",
    fontSize: 13,
    fontFamily: "var(--body)",
    border: "1px solid var(--cream-edge)",
    borderRadius: 8,
  },
};

export default function AdminPanel() {
  const { token, user, logout } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("queue");

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div style={css.page}>
      <div style={css.header}>
        <div>
          <div style={{ fontSize: 11, letterSpacing: 2, color: "var(--forest)", textTransform: "uppercase", fontWeight: 600 }}>
            Painel de administração
          </div>
          <h1 style={css.title}>Olá, {user?.full_name}</h1>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link to="/app" style={{ ...css.btn, textDecoration: "none" }}>Abrir chatbot</Link>
          <button onClick={handleLogout} style={css.btn}>Terminar sessão</button>
        </div>
      </div>

      <div style={css.tabs}>
        <button style={css.tab(tab === "queue")} onClick={() => setTab("queue")}>Fila de especialistas</button>
        <button style={css.tab(tab === "users")} onClick={() => setTab("users")}>Utilizadores</button>
        <button style={css.tab(tab === "invites")} onClick={() => setTab("invites")}>Convites de admin</button>
      </div>

      {tab === "queue" && <SpecialistQueue token={token} />}
      {tab === "users" && <UsersList token={token} />}
      {tab === "invites" && <InvitesPanel token={token} />}
    </div>
  );
}

function useAsyncList(loader, deps = []) {
  const [state, setState] = useState({ loading: true, error: "", items: [] });
  const reload = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const items = await loader();
      setState({ loading: false, error: "", items });
    } catch (err) {
      setState({ loading: false, error: err.message || "Erro ao carregar.", items: [] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}

function SpecialistQueue({ token }) {
  const { loading, error, items, reload } = useAsyncList(
    () => apiJson("/admin/specialist-queue", { token }),
    [token]
  );
  const [actionError, setActionError] = useState("");
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");

  async function handleApprove(id) {
    setActionError("");
    try {
      await apiJson(`/admin/specialists/${id}/approve`, { method: "POST", token });
      await reload();
    } catch (err) {
      setActionError(err.message || "Erro ao aprovar.");
    }
  }

  async function handleReject(id) {
    if (!reason.trim()) {
      setActionError("Indique um motivo.");
      return;
    }
    setActionError("");
    try {
      await apiJson(`/admin/specialists/${id}/reject`, {
        method: "POST",
        token,
        body: { reason: reason.trim() },
      });
      setRejecting(null);
      setReason("");
      await reload();
    } catch (err) {
      setActionError(err.message || "Erro ao rejeitar.");
    }
  }

  async function handleDownload(credId, name) {
    try {
      await apiDownload(`/admin/credentials/${credId}/download`, { token, filename: name });
    } catch (err) {
      setActionError(err.message || "Erro ao descarregar.");
    }
  }

  if (loading) return <div style={css.card}>A carregar...</div>;
  if (error) return <div style={{ ...css.card, color: "#8b2e2e" }}>{error}</div>;
  if (items.length === 0) return <div style={css.card}>Sem especialistas pendentes.</div>;

  return (
    <div>
      {actionError && <div style={{ ...css.card, color: "#8b2e2e" }}>{actionError}</div>}
      {items.map((item) => (
        <div key={item.id} style={css.card}>
          <div style={css.row}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{item.full_name}</div>
              <div style={{ fontSize: 13, color: "var(--ink-muted)" }}>{item.email}</div>
              <div style={{ fontSize: 13, color: "var(--ink-muted)", marginTop: 4 }}>
                {item.specialty} · {item.institution} · {item.country}
              </div>
            </div>
            <span style={css.badge("pending")}>pendente</span>
          </div>
          {item.credentials?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-muted)", marginBottom: 6, letterSpacing: 0.3, textTransform: "uppercase" }}>
                Credenciais submetidas
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {item.credentials.map((c) => (
                  <div key={c.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                    <div style={{ fontSize: 13 }}>{c.original_filename}</div>
                    <button onClick={() => handleDownload(c.id, c.original_filename)} style={css.btn}>
                      Descarregar
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button onClick={() => handleApprove(item.id)} style={css.btnPrimary}>Aprovar</button>
            {rejecting === item.id ? (
              <div style={{ flex: 1, minWidth: 280 }}>
                <textarea
                  style={css.textarea}
                  placeholder="Motivo da rejeição"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <button onClick={() => handleReject(item.id)} style={css.btnDanger}>Confirmar rejeição</button>
                  <button onClick={() => { setRejecting(null); setReason(""); }} style={css.btn}>Cancelar</button>
                </div>
              </div>
            ) : (
              <button onClick={() => { setRejecting(item.id); setReason(""); }} style={css.btnDanger}>Rejeitar</button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function UsersList({ token }) {
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const { loading, error, items, reload } = useAsyncList(() => {
    const params = new URLSearchParams();
    if (role) params.set("role", role);
    if (status) params.set("status", status);
    const qs = params.toString();
    return apiJson(`/admin/users${qs ? `?${qs}` : ""}`, { token });
  }, [token, role, status]);

  return (
    <div>
      <div style={{ ...css.card, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-muted)", letterSpacing: 0.3, textTransform: "uppercase" }}>Filtrar</span>
        <select value={role} onChange={(e) => setRole(e.target.value)} style={css.input}>
          <option value="">Todos os papéis</option>
          <option value="user">Utilizador</option>
          <option value="specialist">Especialista</option>
          <option value="admin">Admin</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={css.input}>
          <option value="">Todos os estados</option>
          <option value="active">Ativo</option>
          <option value="pending">Pendente</option>
          <option value="rejected">Rejeitado</option>
        </select>
        <button onClick={reload} style={css.btn}>Recarregar</button>
      </div>
      {loading && <div style={css.card}>A carregar...</div>}
      {error && <div style={{ ...css.card, color: "#8b2e2e" }}>{error}</div>}
      {!loading && !error && items.length === 0 && <div style={css.card}>Sem utilizadores.</div>}
      {items.map((u) => (
        <div key={u.id} style={css.card}>
          <div style={css.row}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{u.full_name}</div>
              <div style={{ fontSize: 13, color: "var(--ink-muted)" }}>{u.email}</div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <span style={css.badge("neutral")}>{u.role}</span>
              <span style={css.badge(u.status)}>{u.status}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function InvitesPanel({ token }) {
  const { loading, error, items, reload } = useAsyncList(
    () => apiJson("/admin/invites", { token }),
    [token]
  );
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [lastInvite, setLastInvite] = useState(null);

  async function handleCreate(e) {
    e.preventDefault();
    setCreateError("");
    setCreating(true);
    try {
      const res = await apiJson("/admin/invites", {
        method: "POST",
        token,
        body: { note: note.trim() || null },
      });
      setLastInvite(res);
      setNote("");
      await reload();
    } catch (err) {
      setCreateError(err.message || "Erro ao criar convite.");
    } finally {
      setCreating(false);
    }
  }

  const inviteUrl = lastInvite
    ? `${window.location.origin}/invite/${lastInvite.token}`
    : null;

  return (
    <div>
      <form onSubmit={handleCreate} style={css.card}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-muted)", letterSpacing: 0.3, textTransform: "uppercase", marginBottom: 8 }}>
          Gerar novo convite
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ ...css.input, flex: 1, minWidth: 240 }}
            placeholder="Nota (opcional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="submit" disabled={creating} style={{ ...css.btnPrimary, opacity: creating ? 0.7 : 1 }}>
            {creating ? "A gerar..." : "Gerar convite"}
          </button>
        </div>
        {createError && <div style={{ color: "#8b2e2e", fontSize: 13, marginTop: 8 }}>{createError}</div>}
        {lastInvite && (
          <div style={{ marginTop: 12, padding: 12, background: "rgba(31,59,46,0.06)", borderRadius: 8 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--forest)", marginBottom: 6 }}>
              Link de convite (guardar agora — só mostrado uma vez):
            </div>
            <div style={{ fontSize: 13, wordBreak: "break-all", fontFamily: "monospace", background: "var(--paper)", padding: 8, borderRadius: 6 }}>
              {inviteUrl}
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-muted)", marginTop: 6 }}>
              Expira em {new Date(lastInvite.expires_at).toLocaleString()}.
            </div>
          </div>
        )}
      </form>
      {loading && <div style={css.card}>A carregar...</div>}
      {error && <div style={{ ...css.card, color: "#8b2e2e" }}>{error}</div>}
      {!loading && !error && items.length === 0 && <div style={css.card}>Sem convites.</div>}
      {items.map((inv) => {
        const now = new Date();
        const exp = new Date(inv.expires_at);
        const used = !!inv.used_at;
        const expired = !used && exp < now;
        const tone = used ? "neutral" : expired ? "rejected" : "active";
        const label = used ? "usado" : expired ? "expirado" : "ativo";
        return (
          <div key={inv.id} style={css.card}>
            <div style={css.row}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{inv.note || "(sem nota)"}</div>
                <div style={{ fontSize: 12, color: "var(--ink-muted)" }}>
                  Criado {new Date(inv.created_at).toLocaleString()} · Expira {exp.toLocaleString()}
                </div>
                {inv.used_at && (
                  <div style={{ fontSize: 12, color: "var(--ink-muted)" }}>
                    Usado em {new Date(inv.used_at).toLocaleString()}
                  </div>
                )}
              </div>
              <span style={css.badge(tone)}>{label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
