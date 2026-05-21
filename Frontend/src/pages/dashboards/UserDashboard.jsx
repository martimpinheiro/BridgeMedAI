import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiJson } from "../../auth/api.js";
import {
  PageHeader, KPICard, Card, Grid, SectionHeading,
  List, ListRow, StatusPill, Spinner, EmptyState, Button, Hero,
} from "../../components/ui/index.jsx";
import {
  IconChat, IconStack, IconHistory, IconArrowRight, IconSparkle,
} from "../../components/ui/Icons.jsx";

export default function UserDashboard() {
  const { token, user } = useAuth();
  const [metrics, setMetrics] = useState(null);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [m, t] = await Promise.all([
        apiJson("/user/metrics/summary", { token }).catch(() => null),
        // /traceability é filtrado pelo backend ao user logged in — correto aqui
        apiJson("/traceability?limit=8", { token }).catch(() => []),
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

  const firstName = user?.full_name?.split(" ")[0] || "olá";

  return (
    <>
      <Hero
        eyebrow="BridgeMedAI · Copilot regulatório"
        title={<>Olá, <em>{firstName}</em>.<br />Em que posso ajudar hoje?</>}
        lead="Pergunta sobre MDR, AI Act, classificação, gestão de risco, cibersegurança, ou pede para te ajudar a preencher documentação técnica."
        cta={
          <Link to="/user/chat" className="bmui-hero__cta">
            <IconChat size={16} /> Abrir o chatbot
          </Link>
        }
      />

      <Grid cols={3} style={{ marginBottom: 32 }}>
        <KPICard
          label="Conversas"
          value={loading ? "…" : metrics?.activity?.my_chat_messages ?? 0}
          icon={<IconChat size={16} />}
        />
        <KPICard
          label="Documentos em curso"
          value={loading ? "…" : metrics?.copilot?.my_documents_in_progress ?? 0}
          delta={metrics?.copilot?.my_documents_completed ? `${metrics.copilot.my_documents_completed} completos` : ""}
          deltaDir={metrics?.copilot?.my_documents_completed ? "up" : undefined}
          icon={<IconStack size={16} />}
        />
        <KPICard
          label="Documentos gerados"
          value={loading ? "…" : metrics?.activity?.my_documents_generated ?? 0}
          icon={<IconSparkle size={16} />}
        />
      </Grid>

      <Grid cols={2}>
        <Card
          title="Continuar onde paraste"
          subtitle="As tuas últimas conversas e documentos"
        >
          {loading ? (
            <Spinner />
          ) : recent.length === 0 ? (
            <EmptyState
              title="Sem histórico ainda"
              message="Abre o chatbot e começa por descrever o teu dispositivo."
              action={
                <Button as={Link} to="/user/chat">
                  <IconChat size={14} /> Começar agora
                </Button>
              }
            />
          ) : (
            <>
              <SectionHeading>Atividade recente</SectionHeading>
              <List>
                {recent.slice(0, 6).map((t) => (
                  <ListRow
                    key={t.id}
                    primary={
                      t.question
                        ? truncate(t.question, 80)
                        : t.regulatory_step || t.download_name || t.trace_type
                    }
                    meta={`${t.trace_type} · ${(t.created_at || "").slice(0, 16).replace("T", " ")}`}
                    actions={
                      <Button as={Link} to="/user/chat" size="small" variant="ghost">
                        Abrir
                      </Button>
                    }
                  />
                ))}
              </List>
              <div style={{ marginTop: 14 }}>
                <Button as={Link} to="/user/history" variant="ghost" size="small">
                  Ver histórico completo <IconArrowRight size={12} />
                </Button>
              </div>
            </>
          )}
        </Card>

        <Card
          title="Templates regulatórios"
          subtitle="35+ templates Fraunhofer prontos a usar"
        >
          <p style={{ margin: "0 0 16px", fontSize: 13.5, color: "var(--ink-muted)", lineHeight: 1.55 }}>
            CER, PMCF, Risk Management, Cybersecurity, Software (IEC 62304),
            Usability (IEC 62366), Vigilance, CAPA…
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Button as={Link} to="/user/templates">
              <IconStack size={14} /> Ver catálogo
            </Button>
            <Button as={Link} to="/user/chat" variant="ghost">
              Pedir sugestão no chat
            </Button>
          </div>
        </Card>
      </Grid>

      <div style={{ marginTop: 24 }}>
        <Card variant="quiet">
          <SectionHeading>Como funciona</SectionHeading>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
            <Step n={1} title="Conversa" text="Descreve o teu dispositivo no chat. O assistant responde com base em MDR e AI Act." />
            <Step n={2} title="Sugestões" text="O sistema deteta de que documentos precisas e propõe templates relevantes." />
            <Step n={3} title="Preenchimento" text="Aceita 'Preencher por mim' e o assistant guia-te pelas perguntas exatas que faltam no template." />
          </div>
        </Card>
      </div>
    </>
  );
}

function Step({ n, title, text }) {
  return (
    <div>
      <div style={{
        fontFamily: "var(--display)", fontSize: 32, fontWeight: 600, color: "var(--forest)",
        lineHeight: 1, marginBottom: 8,
      }}>
        {n}
      </div>
      <div style={{ fontFamily: "var(--display)", fontSize: 16, color: "var(--forest-deep)", marginBottom: 4 }}>
        {title}
      </div>
      <p style={{ margin: 0, fontSize: 13, color: "var(--ink-muted)", lineHeight: 1.55 }}>{text}</p>
    </div>
  );
}

function truncate(s, max) {
  if (!s) return "";
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}
