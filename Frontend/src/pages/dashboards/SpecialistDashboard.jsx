import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import {
  PageHeader, KPICard, Card, Grid, SectionHeading,
  List, ListRow, StatusPill, Spinner, EmptyState, Button,
} from "../../components/ui/index.jsx";
import {
  IconInbox, IconCheckList, IconClock, IconActivity, IconArrowRight, IconScroll,
} from "../../components/ui/Icons.jsx";

export default function SpecialistDashboard() {
  const { token, user } = useAuth();
  const [metrics, setMetrics] = useState(null);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [m, t] = await Promise.all([
        apiJson("/specialist/metrics/summary", { token }).catch(() => null),
        // Para o especialista a fila vem do endpoint global (não as suas
        // próprias entradas — ele não cria, só revê).
        apiJson("/specialist/traceability?limit=20", { token }).catch(() => []),
      ]);
      setMetrics(m);
      setRecent(t || []);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { reload(); }, [reload]);

  // Auto-refresh ao voltar à tab
  useEffect(() => {
    const onFocus = () => reload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reload]);

  return (
    <>
      <PageHeader
        crumb="Especialista · Visão geral"
        title={<>Bom dia, <em>{user?.full_name?.split(" ")[0] || "colega"}</em></>}
        sub="Resumo da tua fila, validações pendentes e atividade recente."
        actions={
          <Button variant="ghost" size="small" onClick={reload}>
            Recarregar
          </Button>
        }
      />

      <Grid cols={4} style={{ marginBottom: 32 }}>
        <KPICard
          label="Pendentes para rever"
          value={loading ? "…" : metrics?.queue?.pending_review ?? 0}
          delta={metrics?.queue?.pending_review > 0 ? "ação requerida" : "fila limpa"}
          deltaDir={metrics?.queue?.pending_review > 0 ? "down" : "up"}
          icon={<IconInbox size={16} />}
        />
        <KPICard
          label="Revisões hoje"
          value={loading ? "…" : metrics?.personal?.reviews_today ?? 0}
          icon={<IconCheckList size={16} />}
        />
        <KPICard
          label="Total revisões"
          value={loading ? "…" : metrics?.personal?.reviews_total ?? 0}
          icon={<IconActivity size={16} />}
        />
        <KPICard
          label="Taxa de aprovação"
          value={
            loading ? "…"
              : metrics?.personal?.approval_rate_pct == null
                ? "—"
                : metrics.personal.approval_rate_pct
          }
          unit={metrics?.personal?.approval_rate_pct == null ? "" : "%"}
          icon={<IconClock size={16} />}
        />
      </Grid>

      <Grid cols={2}>
        <Card
          title="Próximos da tua fila"
          subtitle="Outputs marcados para revisão"
        >
          {loading ? (
            <Spinner label="A carregar fila" />
          ) : recent.filter((t) => !t.result).length === 0 ? (
            <EmptyState
              title="Fila limpa"
              message="Sem outputs por rever. Bom trabalho — volta noutro momento."
            />
          ) : (
            <>
              <SectionHeading>Top 5</SectionHeading>
              <List>
                {recent
                  .filter((t) => !t.result)
                  .slice(0, 5)
                  .map((t) => (
                    <ListRow
                      key={t.id}
                      primary={t.question || t.regulatory_step || t.trace_type}
                      meta={`${t.trace_type} · ${(t.created_at || "").slice(0, 16).replace("T", " ")}`}
                      actions={
                        <Button
                          as={Link}
                          to="/specialist/validation"
                          size="small"
                          variant="ghost"
                        >
                          Rever
                        </Button>
                      }
                    />
                  ))}
              </List>
              <div style={{ marginTop: 14 }}>
                <Button as={Link} to="/specialist/queue" variant="ghost" size="small">
                  Abrir fila completa <IconArrowRight size={12} />
                </Button>
              </div>
            </>
          )}
        </Card>

        <Card
          title="Histórico recente"
          subtitle="As tuas últimas validações"
        >
          {loading ? (
            <Spinner />
          ) : recent.filter((t) => t.result).length === 0 ? (
            <EmptyState
              title="Sem histórico ainda"
              message="Aparece aqui o que tu revires."
            />
          ) : (
            <>
              <SectionHeading>Últimas</SectionHeading>
              <List>
                {recent
                  .filter((t) => t.result)
                  .slice(0, 6)
                  .map((t) => (
                    <ListRow
                      key={t.id}
                      primary={t.question || t.regulatory_step || t.trace_type}
                      meta={`${t.trace_type} · ${(t.updated_at || t.created_at || "").slice(0, 16).replace("T", " ")}`}
                      actions={
                        <StatusPill
                          tone={
                            t.result === "OK"
                              ? "ok"
                              : t.result === "NOK"
                              ? "bad"
                              : "info"
                          }
                        >
                          {t.result}
                        </StatusPill>
                      }
                    />
                  ))}
              </List>
              <div style={{ marginTop: 14 }}>
                <Button as={Link} to="/specialist/history" variant="ghost" size="small">
                  Ver histórico completo <IconArrowRight size={12} />
                </Button>
              </div>
            </>
          )}
        </Card>
      </Grid>

      <div style={{ marginTop: 24 }}>
        <Grid cols={3}>
          <ShortcutCard
            to="/specialist/queue"
            title="Fila de revisão"
            description="Outputs do chatbot a aguardar análise."
            icon={<IconInbox size={18} />}
          />
          <ShortcutCard
            to="/specialist/validation"
            title="Validação"
            description="Marcar resultado, severidade e tipo de erro."
            icon={<IconCheckList size={18} />}
          />
          <ShortcutCard
            to="/specialist/matrix"
            title="Matriz regulatória"
            description="Vista agregada por tipo de erro e severidade."
            icon={<IconScroll size={18} />}
          />
        </Grid>
      </div>
    </>
  );
}

function ShortcutCard({ to, title, description, icon }) {
  return (
    <Link to={to} style={{ textDecoration: "none", color: "inherit", display: "block" }}>
      <Card variant="quiet">
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <span style={{
            width: 34, height: 34, borderRadius: 8,
            display: "grid", placeItems: "center",
            background: "var(--sage-light)",
            border: "1px solid var(--sage-deep)",
            color: "var(--forest)",
          }}>
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
