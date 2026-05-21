import React from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import {
  PageHeader, Card, Grid, SectionHeading, StatusPill, Button,
} from "../../components/ui/index.jsx";

export default function SpecialistProfile() {
  const { user, specialistProfile } = useAuth();
  const p = specialistProfile || {};

  return (
    <>
      <PageHeader
        crumb="Especialista · Pessoal"
        title={<>O meu <em>perfil</em></>}
        sub="Informação profissional submetida durante o registo."
      />

      <Grid cols={2}>
        <Card title="Conta">
          <Row label="Nome" value={user?.full_name || "—"} />
          <Row label="Email" value={user?.email || "—"} />
          <Row label="Role" value={<StatusPill tone="forest">{user?.role}</StatusPill>} />
          <Row label="Estado" value={
            <StatusPill tone={user?.status === "active" ? "ok" : user?.status === "pending" ? "warn" : "bad"}>
              {user?.status}
            </StatusPill>
          } />
        </Card>

        <Card title="Perfil profissional">
          <Row label="Áreas de expertise" value={p.specialty || "—"} />
          <Row label="Organização" value={p.institution || "—"} />
          {p.country && <Row label="País" value={p.country} />}
          {p.created_at && (
            <Row label="Registado em" value={new Date(p.created_at).toLocaleDateString()} />
          )}
        </Card>
      </Grid>

      <div style={{ marginTop: 24 }}>
        <Card variant="quiet">
          <SectionHeading>Edição de perfil</SectionHeading>
          <p style={{ margin: "0 0 12px", fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.55 }}>
            Para atualizar as tuas áreas de expertise, organização, ou para
            resubmeter credenciais, contacta o administrador. Numa próxima
            iteração ficará disponível diretamente aqui.
          </p>
          <Button variant="ghost" size="small" disabled>
            Editar perfil (em breve)
          </Button>
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
