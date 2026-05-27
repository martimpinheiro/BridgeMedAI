import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import "../admin/admin.css";
import {
  PageHeader, Card, Grid, SectionHeading, StatusPill, Button, Spinner, EmptyState, KPICard, List, ListRow,
} from "../../components/ui/index.jsx";
import {
  IconUsers, IconChat, IconStack, IconScroll, IconArrowRight,
} from "../../components/ui/Icons.jsx";

export default function UserProfile() {
  const { token, user } = useAuth();
  const [metrics, setMetrics] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [m, p] = await Promise.all([
        apiJson("/user/metrics/summary", { token }).catch(() => null),
        apiJson("/memory/profiles?limit=20", { token }).catch(() => []),
      ]);
      setMetrics(m);
      setProfiles(p || []);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    const onFocus = () => reload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [reload]);

  return (
    <>
      <PageHeader
        crumb="Cliente · Pessoal"
        title={<>O meu <em>perfil</em></>}
        sub="Informação da conta, estatísticas pessoais e perfis de produto criados pelo copiloto."
        actions={
          <Button variant="ghost" size="small" onClick={reload}>
            Recarregar
          </Button>
        }
      />

      <Grid cols={2}>
        <Card title="Conta">
          <Row label="Nome" value={user?.full_name || "—"} />
          <Row label="Email" value={user?.email || "—"} />
          <Row label="Role" value={<StatusPill tone="forest">{user?.role || "user"}</StatusPill>} />
          <Row label="Estado" value={
            <StatusPill tone={user?.status === "active" ? "ok" : "muted"}>{user?.status}</StatusPill>
          } />
        </Card>

        <Card title="Atividade">
          {loading ? (
            <Spinner />
          ) : (
            <>
              <Row label="Conversas no chatbot" value={<strong>{metrics?.activity?.my_chat_messages ?? 0}</strong>} />
              <Row label="Documentos gerados" value={<strong>{metrics?.activity?.my_documents_generated ?? 0}</strong>} />
              <Row label="Perfis de produto" value={<strong>{metrics?.copilot?.my_product_profiles ?? 0}</strong>} />
              <Row label="Documentos em curso" value={<strong>{metrics?.copilot?.my_documents_in_progress ?? 0}</strong>} />
              <Row label="Documentos completos" value={<strong>{metrics?.copilot?.my_documents_completed ?? 0}</strong>} />
            </>
          )}
        </Card>
      </Grid>

      <div style={{ marginTop: 28 }}>
        <Card>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <SectionHeading>Os meus perfis de produto</SectionHeading>
            <Button as={Link} to="/user/chat" variant="ghost" size="small">
              <IconChat size={12} /> Criar via chat
            </Button>
          </div>
          {loading ? (
            <Spinner />
          ) : profiles.length === 0 ? (
            <EmptyState
              title="Sem perfis de produto"
              message="Quando descreves um dispositivo médico no chat, o copiloto cria automaticamente um perfil aqui para reutilizar a informação em documentos."
            />
          ) : (
            <List>
              {profiles.map((p) => (
                <ListRow
                  key={p.id}
                  primary={p.name || "Produto sem nome"}
                  meta={[
                    p.mdr_class && `Classe ${p.mdr_class}`,
                    p.ai_system_flag != null && (p.ai_system_flag ? "Sistema IA" : "Sem IA"),
                    p.updated_at && `atualizado ${(p.updated_at || "").slice(0, 10)}`,
                  ].filter(Boolean).join(" · ")}
                  actions={
                    <Button as={Link} to="/user/chat" size="small" variant="ghost">
                      Abrir <IconArrowRight size={11} />
                    </Button>
                  }
                />
              ))}
            </List>
          )}
        </Card>
      </div>

    </>
  );
}

function Row({ label, value }) {
  return (
    <div style={{
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      padding: "10px 0",
      borderBottom: "1px dashed rgba(21,42,32,0.08)",
    }}>
      <span style={{
        fontFamily: "var(--mono)",
        fontSize: 10,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: "var(--ink-faded)",
      }}>
        {label}
      </span>
      <span style={{ fontFamily: "var(--body)", fontSize: 13.5, color: "var(--ink)" }}>
        {value}
      </span>
    </div>
  );
}
