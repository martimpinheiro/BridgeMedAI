import React, { useMemo, useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "./admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading,
} from "../../components/ui/index.jsx";
import { IconUsers } from "../../components/ui/Icons.jsx";

const ROLE_LABEL = {
  user: "Utilizador",
  specialist: "Especialista",
  admin: "Admin",
};

export default function AdminUsers() {
  const { token } = useAuth();
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");

  const { loading, error, items, reload } = useAsyncList(() => {
    const params = new URLSearchParams();
    if (role) params.set("role", role);
    if (status) params.set("status", status);
    const qs = params.toString();
    return apiJson(`/admin/users${qs ? `?${qs}` : ""}`, { token });
  }, [token, role, status]);

  // filtro de search aplicado client-side
  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.trim().toLowerCase();
    return items.filter((u) =>
      (u.full_name || "").toLowerCase().includes(q) ||
      (u.email || "").toLowerCase().includes(q)
    );
  }, [items, search]);

  const counts = useMemo(() => {
    const c = { active: 0, pending: 0, rejected: 0 };
    for (const u of items) c[u.status] = (c[u.status] || 0) + 1;
    return c;
  }, [items]);

  return (
    <>
      <PageHeader
        crumb="Administração · Pessoas"
        title={<>Gestão de <em>utilizadores</em></>}
        sub={`${items.length} utilizador(es) · ${counts.active || 0} ativos · ${counts.pending || 0} pendentes · ${counts.rejected || 0} rejeitados`}
        actions={
          <Button variant="ghost" size="small" onClick={reload}>Recarregar</Button>
        }
      />

      <div className="admin-filterbar">
        <span className="admin-filterbar__label">Filtrar</span>
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">Todos os papéis</option>
          <option value="user">Utilizador</option>
          <option value="specialist">Especialista</option>
          <option value="admin">Admin</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Todos os estados</option>
          <option value="active">Ativo</option>
          <option value="pending">Pendente</option>
          <option value="rejected">Rejeitado</option>
        </select>
        <input
          type="text"
          placeholder="Procurar por nome ou email…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 220 }}
        />
      </div>

      {loading && <Spinner label="A carregar utilizadores" />}
      {error && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {error}
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          title="Sem utilizadores"
          message={search ? `Nenhum match para "${search}".` : "Nada para mostrar com os filtros atuais."}
        />
      )}

      {filtered.length > 0 && (
        <>
          <SectionHeading>{filtered.length} resultado(s)</SectionHeading>
          {filtered.map((u) => (
            <article key={u.id} className="admin-row">
              <div>
                <div className="admin-row__primary">
                  <IconUsers size={14} style={{ verticalAlign: "middle", marginRight: 6, color: "var(--forest)" }} />
                  {u.full_name}
                </div>
                <div className="admin-row__secondary">{u.email}</div>
              </div>
              <div className="admin-row__pills">
                <StatusPill tone="muted">{ROLE_LABEL[u.role] || u.role}</StatusPill>
                <StatusPill tone={u.status === "active" ? "ok" : u.status === "pending" ? "warn" : u.status === "rejected" ? "bad" : "muted"}>
                  {u.status}
                </StatusPill>
              </div>
            </article>
          ))}
        </>
      )}
    </>
  );
}
