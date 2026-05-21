import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import {
  PageHeader, KPICard, Card, Grid, SectionHeading,
  List, ListRow, StatusPill, Spinner, EmptyState, Button,
} from "../../components/ui/index.jsx";
import {
  IconUsers, IconShield, IconChat, IconScroll, IconActivity, IconArrowRight,
} from "../../components/ui/Icons.jsx";

export default function AdminDashboard() {
  const { token } = useAuth();
  const [metrics, setMetrics] = useState(null);
  const [queue, setQueue] = useState([]);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [m, q, t] = await Promise.all([
        apiJson("/admin/metrics/summary", { token }).catch(() => null),
        apiJson("/admin/specialist-queue", { token }).catch(() => []),
        // /admin/traceability é a vista GLOBAL (não filtrada por user_id)
        apiJson("/admin/traceability?limit=8", { token }).catch(() => []),
      ]);
      setMetrics(m);
      setQueue(q || []);
      setRecent(t || []);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { reload(); }, [reload]);

  // Refresh quando voltas à tab (focus) — apanha alterações feitas noutra página
  useEffect(() => {
    const onFocus = () => reload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reload]);

  return (
    <>
      <PageHeader
        crumb="Administração · Visão geral"
        title={<>Dashboard <em>Admin</em></>}
        sub="Estado da plataforma, candidaturas pendentes e atividade recente."
        actions={
          <Button variant="ghost" size="small" onClick={reload}>
            Recarregar
          </Button>
        }
      />

      <Grid cols={4} style={{ marginBottom: 32 }}>
        <KPICard
          label="Utilizadores"
          value={loading ? "…" : metrics?.users?.total ?? 0}
          delta={metrics ? `${metrics.users?.active ?? 0} ativos` : ""}
          deltaDir="up"
          icon={<IconUsers size={16} />}
        />
        <KPICard
          label="Especialistas"
          value={loading ? "…" : metrics?.specialists?.active ?? 0}
          delta={metrics?.specialists?.pending ? `${metrics.specialists.pending} pendentes` : "0 pendentes"}
          deltaDir={metrics?.specialists?.pending ? "down" : undefined}
          icon={<IconShield size={16} />}
        />
        <KPICard
          label="Chats hoje"
          value={loading ? "…" : metrics?.activity?.chats_today ?? 0}
          icon={<IconChat size={16} />}
        />
        <KPICard
          label="Docs gerados"
          value={loading ? "…" : metrics?.activity?.documents_generated_total ?? 0}
          delta={metrics?.copilot?.documents_in_progress ? `${metrics.copilot.documents_in_progress} em curso` : ""}
          icon={<IconScroll size={16} />}
        />
      </Grid>

      <Grid cols={2}>
        <Card
          title="Candidaturas de especialista pendentes"
          subtitle={`${queue.length} aguarda${queue.length === 1 ? "" : "m"} aprovação`}
        >
          {loading ? (
            <Spinner label="A carregar fila" />
          ) : queue.length === 0 ? (
            <EmptyState
              title="Nada pendente"
              message="Sem candidaturas de especialista a aguardar revisão."
            />
          ) : (
            <>
              <SectionHeading>Fila</SectionHeading>
              <List>
                {queue.slice(0, 5).map((c) => (
                  <ListRow
                    key={c.id || c.user_id}
                    primary={c.full_name || c.email}
                    meta={`${c.specialty || "Especialidade —"} · ${c.institution || "Instituição —"}`}
                    actions={<StatusPill tone="warn">Pending</StatusPill>}
                  />
                ))}
              </List>
              {queue.length > 5 && (
                <div style={{ marginTop: 14 }}>
                  <Button as={Link} to="/admin/specialists" variant="ghost" size="small">
                    Ver todas ({queue.length}) <IconArrowRight size={12} />
                  </Button>
                </div>
              )}
            </>
          )}
        </Card>

        <Card
          title="Atividade recente"
          subtitle="Últimas entradas na matriz de rastreabilidade"
        >
          {loading ? (
            <Spinner label="A carregar" />
          ) : recent.length === 0 ? (
            <EmptyState
              title="Sem atividade ainda"
              message="Quando os utilizadores começarem a interagir, aparece aqui."
            />
          ) : (
            <>
              <SectionHeading>Recente</SectionHeading>
              <List>
                {recent.slice(0, 6).map((t) => (
                  <ListRow
                    key={t.id}
                    primary={
                      t.question || t.regulatory_step || t.download_name || t.trace_type
                    }
                    meta={`${t.trace_type} · ${(t.created_at || "").slice(0, 16).replace("T", " ")}`}
                    actions={
                      t.result ? (
                        <StatusPill
                          tone={
                            t.result === "OK" ? "ok" : t.result === "NOK" ? "bad" : "info"
                          }
                        >
                          {t.result}
                        </StatusPill>
                      ) : (
                        <StatusPill tone="muted">Por rever</StatusPill>
                      )
                    }
                  />
                ))}
              </List>
              <div style={{ marginTop: 14 }}>
                <Button as={Link} to="/admin/matrix" variant="ghost" size="small">
                  Ver matriz completa <IconArrowRight size={12} />
                </Button>
              </div>
            </>
          )}
        </Card>
      </Grid>

      <div style={{ marginTop: 24 }}>
        <Grid cols={3}>
          <ShortcutCard
            to="/admin/specialists"
            title="Gerir especialistas"
            description="Aprovar ou rejeitar candidaturas, ver perfis."
            icon={<IconShield size={18} />}
          />
          <ShortcutCard
            to="/admin/users"
            title="Utilizadores"
            description="Lista global de clientes e empresas."
            icon={<IconUsers size={18} />}
          />
          <ShortcutCard
            to="/admin/matrix"
            title="Matriz regulatória"
            description="Revisão de outputs e qualidade."
            icon={<IconActivity size={18} />}
          />
        </Grid>
      </div>
    </>
  );
}

function ShortcutCard({ to, title, description, icon }) {
  return (
    <Link
      to={to}
      style={{
        textDecoration: "none",
        color: "inherit",
        display: "block",
      }}
    >
      <Card variant="quiet">
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <span
            style={{
              width: 34, height: 34, borderRadius: 8,
              display: "grid", placeItems: "center",
              background: "var(--sage-light)",
              border: "1px solid var(--sage-deep)",
              color: "var(--forest)",
            }}
          >
            {icon}
          </span>
          <h3 style={{ margin: 0, fontFamily: "var(--display)", fontSize: 17, color: "var(--forest-deep)" }}>
            {title}
          </h3>
        </div>
        <p style={{ margin: 0, fontSize: 13, color: "var(--ink-muted)" }}>{description}</p>
        <div style={{ marginTop: 12, display: "inline-flex", alignItems: "center", gap: 6, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--forest)" }}>
          Abrir <IconArrowRight size={11} />
        </div>
      </Card>
    </Link>
  );
}
