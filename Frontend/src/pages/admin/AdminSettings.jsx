import React from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import {
  PageHeader, Card, Grid, StatusPill,
} from "../../components/ui/index.jsx";

export default function AdminSettings() {
  const { user } = useAuth();

  return (
    <>
      <PageHeader
        crumb="Administração · Sistema"
        title={<>Configurações</>}
        sub="Informação da conta de admin e ligações dos serviços externos (read-only por agora)."
      />

      <Grid cols={2}>
        <Card title="Conta de admin">
          <Row label="Nome" value={user?.full_name || "—"} />
          <Row label="Email" value={user?.email || "—"} />
          <Row label="Role" value={<StatusPill tone="forest">{user?.role}</StatusPill>} />
          <Row label="Estado" value={<StatusPill tone={user?.status === "active" ? "ok" : "muted"}>{user?.status}</StatusPill>} />
        </Card>

        <Card title="Serviços externos">
          <Row label="Backend FastAPI" value={<StatusPill tone="ok">a correr</StatusPill>} />
          <Row label="SQL Server" value={<code style={code}>localhost · BridgeMedAI</code>} />
          <Row label="ChromaDB" value={<code style={code}>127.0.0.1:8002</code>} />
          <Row label="Ollama" value={<code style={code}>localhost:11434</code>} />
        </Card>
      </Grid>

    </>
  );
}

const code = {
  fontFamily: "var(--mono)",
  fontSize: 12,
  background: "var(--cream)",
  border: "1px solid var(--cream-edge)",
  borderRadius: 6,
  padding: "2px 8px",
  color: "var(--forest)",
};

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px dashed rgba(21,42,32,0.08)" }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--ink-faded)" }}>
        {label}
      </span>
      <span style={{ fontFamily: "var(--body)", fontSize: 13.5, color: "var(--ink)" }}>
        {value}
      </span>
    </div>
  );
}
