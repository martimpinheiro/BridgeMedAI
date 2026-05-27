import React, { useMemo } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "./admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, KPICard, Grid,
} from "../../components/ui/index.jsx";
import {
  IconActivity, IconChat, IconScroll, IconAlert,
} from "../../components/ui/Icons.jsx";

export default function AdminLogs() {
  const { token } = useAuth();
  const metrics = useAsyncList(
    () => apiJson("/admin/metrics/summary", { token }).then((d) => [d]),
    [token]
  );
  const recent = useAsyncList(
    () => apiJson("/admin/traceability?limit=50", { token }),
    [token]
  );

  const m = metrics.items[0] || null;

  const breakdown = useMemo(() => {
    const b = { chat: 0, regulatory_analysis: 0, regulatory_document: 0 };
    for (const e of recent.items) b[e.trace_type] = (b[e.trace_type] || 0) + 1;
    return b;
  }, [recent.items]);

  const errorRows = useMemo(() => {
    return recent.items
      .filter((e) => e.result === "NOK" || e.severity === "alta")
      .slice(0, 10);
  }, [recent.items]);

  return (
    <>
      <PageHeader
        crumb="Administração · Qualidade"
        title={<>Logs & <em>métricas</em></>}
        sub="Estado agregado da plataforma e atividade recente. Inclui erros marcados a alta severidade."
        actions={
          <Button variant="ghost" size="small" onClick={() => { metrics.reload(); recent.reload(); }}>
            Recarregar
          </Button>
        }
      />

      {metrics.loading ? (
        <Spinner label="A carregar métricas" />
      ) : (
        <Grid cols={4} style={{ marginBottom: 24 }}>
          <KPICard label="Utilizadores totais" value={m?.users?.total ?? 0} icon={<IconActivity size={16} />} />
          <KPICard label="Chats hoje" value={m?.activity?.chats_today ?? 0} icon={<IconChat size={16} />} />
          <KPICard label="Docs gerados (total)" value={m?.activity?.documents_generated_total ?? 0} icon={<IconScroll size={16} />} />
          <KPICard
            label="Matriz por rever"
            value={m?.activity?.matrix_pending_review ?? 0}
            deltaDir={m?.activity?.matrix_pending_review > 0 ? "down" : "up"}
            delta={m?.activity?.matrix_pending_review > 0 ? "requer atenção" : "tudo revisto"}
            icon={<IconAlert size={16} />}
          />
        </Grid>
      )}

      <Grid cols={2}>
        <Card title="Distribuição por tipo (últimas 50)">
          {recent.loading ? (
            <Spinner />
          ) : (
            <>
              <DistRow label="Chat (RAG)" value={breakdown.chat} total={recent.items.length} />
              <DistRow label="Análise regulatória" value={breakdown.regulatory_analysis} total={recent.items.length} />
              <DistRow label="Geração de documento" value={breakdown.regulatory_document} total={recent.items.length} />
            </>
          )}
        </Card>

        <Card title="Erros recentes (NOK ou severidade alta)" subtitle="Top 10">
          {recent.loading ? (
            <Spinner />
          ) : errorRows.length === 0 ? (
            <EmptyState
              title="Sem erros recentes"
              message="Nada marcado como NOK ou severidade alta nas últimas 50 entradas."
            />
          ) : (
            errorRows.map((e) => (
              <div key={e.id} style={{ padding: "10px 0", borderBottom: "1px dashed rgba(21,42,32,0.08)" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <div style={{ fontFamily: "var(--display)", fontSize: 14, color: "var(--forest-deep)", lineHeight: 1.3 }}>
                    {(e.question || e.regulatory_step || e.trace_type || "—").slice(0, 100)}
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {e.result && (
                      <StatusPill tone={e.result === "NOK" ? "bad" : "warn"}>{e.result}</StatusPill>
                    )}
                    {e.severity === "alta" && <StatusPill tone="bad">alta</StatusPill>}
                  </div>
                </div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.04em", color: "var(--ink-faded)", marginTop: 4, textTransform: "uppercase" }}>
                  {e.trace_type} · {(e.created_at || "").slice(0, 16).replace("T", " ")}
                </div>
              </div>
            ))
          )}
        </Card>
      </Grid>

    </>
  );
}

function DistRow({ label, value, total }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  return (
    <div style={{ padding: "10px 0", borderBottom: "1px dashed rgba(21,42,32,0.08)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <span style={{ fontFamily: "var(--body)", fontSize: 13.5, color: "var(--forest-deep)" }}>{label}</span>
        <span style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--ink-muted)" }}>
          {value} <span style={{ color: "var(--ink-faded)" }}>· {pct}%</span>
        </span>
      </div>
      <div style={{ height: 4, background: "rgba(21,42,32,0.08)", borderRadius: 999, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: "linear-gradient(90deg, var(--forest), var(--forest-soft))", transition: "width 320ms ease" }} />
      </div>
    </div>
  );
}
