import React, { useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "./admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading,
} from "../../components/ui/index.jsx";

export default function AdminInvites() {
  const { token } = useAuth();
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
        method: "POST", token, body: { note: note.trim() || null },
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

  const inviteUrl = lastInvite ? `${window.location.origin}/invite/${lastInvite.token}` : null;

  return (
    <>
      <PageHeader
        crumb="Administração · Pessoas"
        title={<>Convites de <em>admin</em></>}
        sub="Gerar links de registo únicos. Cada convite só pode ser usado uma vez e expira passado algum tempo."
        actions={
          <Button variant="ghost" size="small" onClick={reload}>Recarregar</Button>
        }
      />

      <Card title="Gerar novo convite">
        <form onSubmit={handleCreate} style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "stretch" }}>
          <input
            type="text"
            placeholder="Nota interna (opcional) — quem vai usar este convite?"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            style={{
              flex: 1, minWidth: 260,
              fontFamily: "var(--body)", fontSize: 13,
              padding: "10px 12px", borderRadius: 8,
              border: "1px solid var(--cream-edge)",
              background: "var(--paper)", color: "var(--ink)",
            }}
          />
          <Button type="submit" disabled={creating}>
            {creating ? "A gerar…" : "Gerar convite"}
          </Button>
        </form>

        {createError && (
          <div style={{ marginTop: 10, color: "var(--missing)", fontSize: 13 }}>{createError}</div>
        )}

        {lastInvite && (
          <div className="admin-invite-link">
            <div className="admin-invite-link__label">
              Link de convite — copia agora; só é mostrado uma vez
            </div>
            <div className="admin-invite-link__url">{inviteUrl}</div>
            <div className="admin-invite-link__expiry">
              Expira em {new Date(lastInvite.expires_at).toLocaleString()}
            </div>
            <div style={{ marginTop: 10 }}>
              <Button
                size="small"
                variant="ghost"
                onClick={async () => {
                  try { await navigator.clipboard.writeText(inviteUrl); } catch (_e) {}
                }}
              >
                Copiar link
              </Button>
            </div>
          </div>
        )}
      </Card>

      <div style={{ height: 24 }} />

      {loading && <Spinner label="A carregar convites" />}
      {error && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {error}
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <EmptyState
          title="Sem convites emitidos"
          message="Quando gerares convites para futuros admins aparecem aqui com o respetivo estado."
        />
      )}

      {items.length > 0 && (
        <>
          <SectionHeading>{items.length} convite(s) emitidos</SectionHeading>
          {items.map((inv) => {
            const now = new Date();
            const exp = new Date(inv.expires_at);
            const used = !!inv.used_at;
            const expired = !used && exp < now;
            const tone = used ? "muted" : expired ? "bad" : "ok";
            const label = used ? "Usado" : expired ? "Expirado" : "Ativo";
            return (
              <article key={inv.id} className="admin-row">
                <div>
                  <div className="admin-row__primary">{inv.note || "(sem nota)"}</div>
                  <div className="admin-row__meta">
                    Criado {new Date(inv.created_at).toLocaleString()} · Expira {exp.toLocaleString()}
                  </div>
                  {inv.used_at && (
                    <div className="admin-row__meta">
                      Usado em {new Date(inv.used_at).toLocaleString()}
                    </div>
                  )}
                </div>
                <div className="admin-row__pills">
                  <StatusPill tone={tone}>{label}</StatusPill>
                </div>
              </article>
            );
          })}
        </>
      )}
    </>
  );
}
