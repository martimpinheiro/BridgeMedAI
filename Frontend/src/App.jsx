import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Plus,
  MessageSquare,
  Send,
  AlertCircle,
  FileText,
  Trash2,
  ShieldCheck,
  Upload,
  Download,
  ClipboardCheck,
  CheckCircle2,
} from "lucide-react";

/* inline icon set — version-agnostic, visually cohesive with the design system */
const Svg = ({ size = 16, children, strokeWidth = 1.7, ...rest }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden
    {...rest}
  >
    {children}
  </svg>
);

const Menu = (p) => (
  <Svg {...p}>
    <line x1="4" y1="7" x2="20" y2="7" />
    <line x1="4" y1="12" x2="20" y2="12" />
    <line x1="4" y1="17" x2="14" y2="17" />
  </Svg>
);

const Activity = (p) => (
  <Svg {...p}>
    <polyline points="3,12 7,12 10,5 14,19 17,12 21,12" />
  </Svg>
);

const Scale = (p) => (
  <Svg {...p}>
    <path d="M12 3v18" />
    <path d="M5 7h14" />
    <path d="M7 7l-3 7a4 4 0 0 0 6 0z" />
    <path d="M17 7l-3 7a4 4 0 0 0 6 0z" />
    <path d="M8 21h8" />
  </Svg>
);

const ChevronDown = (p) => (
  <Svg {...p}>
    <polyline points="6,9 12,15 18,9" />
  </Svg>
);

const ChevronRight = (p) => (
  <Svg {...p}>
    <polyline points="9,6 15,12 9,18" />
  </Svg>
);

const Stethoscope = (p) => (
  <Svg {...p}>
    <path d="M5 3v6a4 4 0 0 0 8 0V3" />
    <path d="M4 3h2" />
    <path d="M12 3h2" />
    <path d="M9 13v3a4 4 0 0 0 8 0v-1" />
    <circle cx="18" cy="12" r="2.3" />
  </Svg>
);

const BookOpen = (p) => (
  <Svg {...p}>
    <path d="M3 5.5a2 2 0 0 1 2-2h5v16H5a2 2 0 0 1-2-2z" />
    <path d="M21 5.5a2 2 0 0 0-2-2h-5v16h5a2 2 0 0 0 2-2z" />
  </Svg>
);

const ListChecks = (p) => (
  <Svg {...p}>
    <polyline points="3,6 4.5,7.5 7,5" />
    <polyline points="3,12 4.5,13.5 7,11" />
    <polyline points="3,18 4.5,19.5 7,17" />
    <line x1="11" y1="6" x2="20" y2="6" />
    <line x1="11" y1="12" x2="20" y2="12" />
    <line x1="11" y1="18" x2="20" y2="18" />
  </Svg>
);

const Sparkles = (p) => (
  <Svg {...p}>
    <path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z" />
    <path d="M18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z" />
  </Svg>
);

const Check = (p) => (
  <Svg {...p} strokeWidth={p.strokeWidth || 2.6}>
    <polyline points="5,12 10,17 19,7" />
  </Svg>
);

const CircleDashed = (p) => (
  <Svg {...p}>
    <path d="M10.1 3.2a9 9 0 0 1 3.8 0" />
    <path d="M17.1 5a9 9 0 0 1 2 2.1" />
    <path d="M20.8 10.1a9 9 0 0 1 0 3.8" />
    <path d="M19 17.1a9 9 0 0 1-2 2" />
    <path d="M13.9 20.8a9 9 0 0 1-3.8 0" />
    <path d="M7 19a9 9 0 0 1-2-2" />
    <path d="M3.2 13.9a9 9 0 0 1 0-3.8" />
    <path d="M5 7a9 9 0 0 1 2-2" />
  </Svg>
);

/* ---------- constants ---------- */
const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const STORAGE_KEY = "bridgemedai_chat_state_v1";

const INTENT_LABELS = {
  regulatory_scope: "Enquadramento regulatório",
  classification_risk: "Classificação e risco",
  documentation: "Documentação técnica",
  conformity_procedure: "Procedimento de conformidade",
  requirement_lookup: "Consulta de requisitos",
};

const DOC_LABELS = {
  MDR: "MDR 2017/745",
  AI_ACT: "AI Act 2024/1689",
  GDPR: "GDPR",
  ISO13485: "ISO 13485",
};

const SUGGESTIONS = [
  {
    icon: Scale,
    title: "Enquadramento",
    q: "Que regulamentos preciso de cumprir para um dispositivo médico com IA?",
  },
  {
    icon: Stethoscope,
    title: "Classificação",
    q: "Como classificar um termómetro digital com componente de IA segundo o MDR?",
  },
  {
    icon: BookOpen,
    title: "Documentação",
    q: "Que documentação técnica é exigida pelo MDR para um dispositivo Classe IIa?",
  },
  {
    icon: ListChecks,
    title: "Procedimento",
    q: "Quais são os passos do procedimento de avaliação da conformidade?",
  },
];

/* ---------- helpers ---------- */
function createConversation(title = "Nova conversa", mode = "rag") {
  return {
    id: crypto.randomUUID(),
    title,
    mode, // "rag" | "regulatory"
    messages: [],
    meta: null,
    regulatory: mode === "regulatory"
      ? {
          sessionId: null,
          step: "awaiting_description",
          pendingAction: null,
          lastAnalysis: null,
          filledFields: [],
          flaggedFields: [],
          downloadUrl: null,
          downloadName: null,
          customTemplateName: null,
        }
      : null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

const REGULATORY_STEPS = [
  { key: "awaiting_description", short: "Análise", long: "1. Análise do dispositivo" },
  { key: "awaiting_fill_confirmation", short: "Confirmar", long: "Confirmar PMCF" },
  { key: "collecting_info", short: "Recolha", long: "2. Recolha de informação" },
  { key: "document_ready", short: "Documento", long: "3. Documento pronto" },
];

function regulatoryStepIndex(step) {
  if (step === "awaiting_description") return 0;
  if (step === "awaiting_fill_confirmation") return 0.5;
  if (step === "collecting_info") return 1;
  if (step === "document_ready") return 2;
  return 0;
}

function formatConversationTitle(text) {
  if (!text) return "Nova conversa";
  return text.length > 42 ? `${text.slice(0, 42)}...` : text;
}

function stripInlineWrappers(text) {
  let t = text;
  const boldWrap = t.match(/^\*\*(.+)\*\*$/);
  if (boldWrap) t = boldWrap[1];
  return t.trim();
}

function parseAnswer(raw) {
  if (!raw) return [];
  const lines = raw.replace(/\r/g, "").split("\n");
  const blocks = [];
  let current = null;

  const flushCurrent = () => {
    if (current) {
      blocks.push(current);
      current = null;
    }
  };

  for (let line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      flushCurrent();
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      flushCurrent();
      continue;
    }

    const headingMatch = trimmed.match(/^#{1,6}\s+(.+)$/);
    if (headingMatch) {
      flushCurrent();
      blocks.push({ type: "heading", title: stripInlineWrappers(headingMatch[1]) });
      continue;
    }

    const sectionMatch = trimmed.match(/^(\d+)[\.\)]\s+(.+)$/);
    if (sectionMatch) {
      flushCurrent();
      blocks.push({
        type: "section",
        number: sectionMatch[1],
        title: stripInlineWrappers(sectionMatch[2]),
      });
      continue;
    }

    if (/^[-•*]\s+/.test(trimmed)) {
      const bulletText = trimmed.replace(/^[-•*]\s+/, "");
      if (current && current.type === "list") {
        current.items.push(bulletText);
      } else {
        flushCurrent();
        current = { type: "list", items: [bulletText] };
      }
      continue;
    }

    if (current && current.type === "paragraph") {
      current.text += " " + trimmed;
    } else {
      flushCurrent();
      current = { type: "paragraph", text: trimmed };
    }
  }
  flushCurrent();
  return blocks;
}

function renderInline(text) {
  if (!text) return null;
  const tokens = [];
  const regex = /(\*\*[^*]+\*\*|`[^`]+`|(?<![A-Za-z0-9])_[^_\n]+_(?![A-Za-z0-9])|(?<![A-Za-z0-9*])\*[^*\n]+\*(?![A-Za-z0-9*]))/g;
  let last = 0;
  let m;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) tokens.push({ kind: "text", value: text.slice(last, m.index) });
    const s = m[0];
    if (s.startsWith("**")) tokens.push({ kind: "bold", value: s.slice(2, -2) });
    else if (s.startsWith("`")) tokens.push({ kind: "code", value: s.slice(1, -1) });
    else tokens.push({ kind: "em", value: s.slice(1, -1) });
    last = m.index + s.length;
  }
  if (last < text.length) tokens.push({ kind: "text", value: text.slice(last) });
  return tokens.map((t, i) => {
    if (t.kind === "bold") return <strong key={i}>{t.value}</strong>;
    if (t.kind === "em") return <em key={i}>{t.value}</em>;
    if (t.kind === "code") {
      return (
        <code
          key={i}
          style={{
            fontFamily: "var(--mono, ui-monospace, SFMono-Regular, monospace)",
            fontSize: "0.92em",
            background: "rgba(21,42,32,0.07)",
            padding: "1px 5px",
            borderRadius: 4,
          }}
        >
          {t.value}
        </code>
      );
    }
    return <span key={i}>{t.value}</span>;
  });
}

function averageScore(sources) {
  if (!sources || sources.length === 0) return 0;
  const sum = sources.reduce((acc, s) => acc + (Number(s.score_adjusted) || 0), 0);
  return sum / sources.length;
}

function docLabel(code) {
  return DOC_LABELS[code] || code;
}

function intentLabel(intent) {
  return INTENT_LABELS[intent] || intent || "Pergunta livre";
}

/* ---------- atoms ---------- */
function Logo({ size = 22, tone = "light" }) {
  const fg = tone === "light" ? "#efe9d4" : "#1f3b2e";
  const bg = tone === "light" ? "#2a4f3e" : "#cdddc0";
  return (
    <div
      style={{
        width: size + 14,
        height: size + 14,
        borderRadius: 10,
        background: bg,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
        <rect x="2" y="2" width="9" height="9" rx="1.6" fill={fg} opacity="0.55" />
        <rect x="13" y="2" width="9" height="9" rx="1.6" fill={fg} />
        <rect x="2" y="13" width="9" height="9" rx="1.6" fill={fg} />
        <rect x="13" y="13" width="9" height="9" rx="1.6" fill={fg} opacity="0.35" />
      </svg>
    </div>
  );
}

function Dot({ color = "var(--ink-faded)", size = 7 }) {
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        display: "inline-block",
      }}
    />
  );
}

function StatusPill({ tone = "neutral", children, icon = null }) {
  const tones = {
    neutral: { bg: "rgba(21,42,32,0.06)", color: "var(--ink)", bd: "rgba(21,42,32,0.12)" },
    check: { bg: "rgba(47,122,61,0.12)", color: "var(--check)", bd: "rgba(47,122,61,0.28)" },
    pending: { bg: "rgba(184,117,58,0.12)", color: "var(--pending)", bd: "rgba(184,117,58,0.32)" },
    partial: { bg: "rgba(154,88,38,0.12)", color: "var(--partial)", bd: "rgba(154,88,38,0.32)" },
    missing: { bg: "rgba(162,45,45,0.12)", color: "var(--missing)", bd: "rgba(162,45,45,0.30)" },
    info: { bg: "rgba(58,106,107,0.12)", color: "var(--info)", bd: "rgba(58,106,107,0.32)" },
    forest: { bg: "var(--forest)", color: "var(--paper)", bd: "var(--forest)" },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: "var(--r-pill)",
        background: t.bg,
        color: t.color,
        border: `1px solid ${t.bd}`,
        fontSize: 12,
        fontWeight: 500,
        letterSpacing: 0.1,
        lineHeight: 1.2,
        whiteSpace: "nowrap",
      }}
    >
      {icon}
      {children}
    </span>
  );
}

function HealthIndicator({ state }) {
  const colors = {
    idle: "var(--ink-faded)",
    ok: "var(--check)",
    error: "var(--missing)",
    loading: "var(--pending)",
  };
  const labels = {
    idle: "Sem verificação",
    ok: "Backend online",
    error: "Sem ligação",
    loading: "A verificar...",
  };
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        borderRadius: "var(--r-pill)",
        background: "rgba(31,59,46,0.06)",
        border: "1px solid rgba(31,59,46,0.12)",
        fontSize: 12,
        fontWeight: 500,
        color: "var(--ink-muted)",
      }}
    >
      <Dot color={colors[state] || colors.idle} size={8} />
      {labels[state] || labels.idle}
    </div>
  );
}

/* ---------- KPI bar ---------- */
function Donut({ value = 0, size = 44 }) {
  const v = Math.max(0, Math.min(1, value));
  const r = (size - 4) / 2;
  const circ = 2 * Math.PI * r;
  const dash = v * circ;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke="rgba(21,42,32,0.1)"
        strokeWidth="3"
        fill="none"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke="var(--forest)"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
        strokeDasharray={`${dash} ${circ - dash}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray 600ms ease" }}
      />
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="central"
        fontFamily="var(--mono)"
        fontSize="11"
        fill="var(--forest)"
        fontWeight="600"
      >
        {Math.round(v * 100)}%
      </text>
    </svg>
  );
}

function KpiBar({ meta }) {
  if (!meta) return null;

  const avg = averageScore(meta.generation_sources || []);
  const docs = meta.target_docs || [];
  const sources = meta.generation_sources || [];

  return (
    <section
      className="bmai-stagger"
      style={{
        display: "grid",
        gridTemplateColumns: "1.2fr 1fr 1fr",
        gap: 12,
        marginTop: 6,
      }}
    >
      <KpiCard
        label="Âmbito regulatório"
        value={
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {docs.length ? (
              docs.map((d) => (
                <StatusPill key={d} tone="forest">
                  {docLabel(d)}
                </StatusPill>
              ))
            ) : (
              <span style={{ color: "var(--ink-faded)", fontSize: 13 }}>Não identificado</span>
            )}
          </div>
        }
        hint={intentLabel(meta.intent)}
        icon={<Scale size={16} />}
      />
      <KpiCard
        label="Confiança das fontes"
        value={
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Donut value={avg} />
            <div>
              <div style={{ fontFamily: "var(--display)", fontSize: 22, lineHeight: 1 }}>
                {Math.round(avg * 100)}
                <span style={{ fontSize: 13, color: "var(--ink-muted)" }}> / 100</span>
              </div>
              <div style={{ fontSize: 11, color: "var(--ink-faded)", marginTop: 4 }}>
                score médio ajustado
              </div>
            </div>
          </div>
        }
        icon={<Activity size={16} />}
      />
      <KpiCard
        label="Fontes utilizadas"
        value={
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontFamily: "var(--display)", fontSize: 28, lineHeight: 1 }}>
              {sources.length}
            </span>
            <span style={{ fontSize: 12, color: "var(--ink-muted)" }}>
              de {(meta.retrieved_sources || []).length} recuperadas
            </span>
          </div>
        }
        hint={
          avg >= 0.5
            ? "Resposta fundamentada"
            : avg >= 0.36
            ? "Confiança moderada"
            : "Confiança baixa"
        }
        icon={<ShieldCheck size={16} />}
      />
    </section>
  );
}

function KpiCard({ label, value, hint, icon }) {
  return (
    <div
      style={{
        position: "relative",
        background: "var(--paper)",
        border: "1px solid var(--cream-edge)",
        borderRadius: "var(--r-lg)",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minHeight: 84,
        overflow: "hidden",
      }}
      className="bmai-noise"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          color: "var(--ink-muted)",
          fontSize: 12,
          letterSpacing: 0.3,
          textTransform: "uppercase",
          fontWeight: 500,
        }}
      >
        {icon}
        {label}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>{value}</div>
      {hint && (
        <div style={{ fontSize: 11, color: "var(--ink-faded)", marginTop: "auto" }}>{hint}</div>
      )}
    </div>
  );
}

/* ---------- answer rendering ---------- */
function AnswerRenderer({ text }) {
  const blocks = useMemo(() => parseAnswer(text), [text]);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {blocks.map((b, i) => {
        if (b.type === "section") {
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 14,
                marginTop: i === 0 ? 0 : 10,
                paddingTop: i === 0 ? 0 : 12,
                borderTop: i === 0 ? "none" : "1px dashed rgba(21,42,32,0.14)",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--display)",
                  fontSize: 32,
                  fontVariationSettings: '"opsz" 96, "SOFT" 80',
                  color: "var(--forest)",
                  fontStyle: "italic",
                  lineHeight: 1,
                  flexShrink: 0,
                  letterSpacing: "-0.02em",
                }}
              >
                {b.number}
              </span>
              <h3
                style={{
                  fontFamily: "var(--display)",
                  fontSize: 19,
                  fontWeight: 500,
                  color: "var(--ink)",
                  margin: 0,
                  lineHeight: 1.2,
                }}
              >
                {renderInline(b.title)}
              </h3>
            </div>
          );
        }
        if (b.type === "heading") {
          return (
            <h4
              key={i}
              style={{
                fontFamily: "var(--display)",
                fontSize: 16,
                fontWeight: 600,
                color: "var(--forest)",
                margin: 0,
                marginTop: i === 0 ? 0 : 6,
                letterSpacing: "0.01em",
              }}
            >
              {renderInline(b.title)}
            </h4>
          );
        }
        if (b.type === "list") {
          return (
            <ul
              key={i}
              style={{
                margin: 0,
                padding: 0,
                listStyle: "none",
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              {b.items.map((it, k) => (
                <li
                  key={k}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 10,
                    fontSize: 14.5,
                    lineHeight: 1.65,
                    color: "var(--ink)",
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      width: 4,
                      height: 4,
                      borderRadius: "50%",
                      background: "var(--forest)",
                      marginTop: 10,
                      flexShrink: 0,
                    }}
                  />
                  <span>{renderInline(it)}</span>
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p
            key={i}
            style={{
              fontSize: 14.5,
              lineHeight: 1.7,
              color: "var(--ink)",
              margin: 0,
            }}
          >
            {renderInline(b.text)}
          </p>
        );
      })}
    </div>
  );
}

/* ---------- sources checklist table ---------- */
function SourcesChecklist({ retrieved = [], generation = [] }) {
  if (!retrieved.length && !generation.length) return null;

  const genKeys = new Set(generation.map((s) => s.citation_label));
  const seen = new Set();
  const rows = [];

  generation.forEach((s) => {
    const k = s.citation_label || Math.random().toString();
    if (seen.has(k)) return;
    seen.add(k);
    rows.push({ ...s, status: "used" });
  });
  retrieved.forEach((s) => {
    const k = s.citation_label || Math.random().toString();
    if (seen.has(k) || genKeys.has(k)) return;
    seen.add(k);
    rows.push({ ...s, status: "retrieved" });
  });

  return (
    <div
      style={{
        marginTop: 18,
        background: "var(--paper)",
        border: "1px solid var(--cream-edge)",
        borderRadius: "var(--r-lg)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px",
          borderBottom: "1px solid var(--cream-edge)",
          background: "var(--cream)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <ListChecks size={16} color="var(--forest)" />
          <h3
            style={{
              fontFamily: "var(--display)",
              fontSize: 17,
              margin: 0,
              color: "var(--ink)",
            }}
          >
            Checklist de fontes normativas
          </h3>
        </div>
        <span style={{ fontSize: 12, color: "var(--ink-muted)" }}>
          {generation.length} utilizadas / {retrieved.length} recuperadas
        </span>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 13.5,
          }}
        >
          <thead>
            <tr style={{ background: "rgba(21,42,32,0.03)" }}>
              <Th>Requisito</Th>
              <Th>Fonte</Th>
              <Th width={110}>Secção</Th>
              <Th width={110}>Estado</Th>
              <Th width={100} align="right">Score</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={`${r.citation_label}-${i}`}
                style={{
                  borderTop: "1px solid rgba(21,42,32,0.06)",
                }}
              >
                <Td>
                  <div
                    style={{
                      fontWeight: 500,
                      color: "var(--ink)",
                      lineHeight: 1.4,
                    }}
                  >
                    {r.section_title || r.citation_label || "Sem título"}
                  </div>
                  {r.page_start != null && (
                    <div
                      style={{
                        fontSize: 11,
                        color: "var(--ink-faded)",
                        marginTop: 2,
                        fontFamily: "var(--mono)",
                      }}
                    >
                      pp. {r.page_start}
                      {r.page_end && r.page_end !== r.page_start ? `–${r.page_end}` : ""}
                    </div>
                  )}
                </Td>
                <Td>
                  <StatusPill tone="info">{docLabel(r.short_name)}</StatusPill>
                </Td>
                <Td>
                  <span style={{ fontFamily: "var(--mono)", fontSize: 12, color: "var(--ink-muted)" }}>
                    {r.section_number || "—"}
                  </span>
                </Td>
                <Td>
                  {r.status === "used" ? (
                    <StatusPill tone="check" icon={<Check size={12} strokeWidth={3} />}>
                      Utilizada
                    </StatusPill>
                  ) : (
                    <StatusPill tone="pending" icon={<CircleDashed size={12} />}>
                      Consultada
                    </StatusPill>
                  )}
                </Td>
                <Td align="right">
                  <ScoreBar value={Number(r.score_adjusted) || 0} />
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({ children, width, align = "left" }) {
  return (
    <th
      style={{
        textAlign: align,
        width,
        padding: "10px 18px",
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: 0.4,
        textTransform: "uppercase",
        color: "var(--ink-muted)",
      }}
    >
      {children}
    </th>
  );
}

function Td({ children, align = "left" }) {
  return (
    <td
      style={{
        padding: "12px 18px",
        textAlign: align,
        verticalAlign: "middle",
        color: "var(--ink)",
      }}
    >
      {children}
    </td>
  );
}

function ScoreBar({ value }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div
      style={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: 4,
        minWidth: 80,
      }}
    >
      <span
        style={{
          fontFamily: "var(--mono)",
          fontSize: 12,
          color: "var(--ink)",
          fontWeight: 500,
        }}
      >
        {value.toFixed(3)}
      </span>
      <div
        style={{
          width: 70,
          height: 3,
          background: "rgba(21,42,32,0.08)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: "var(--forest)",
            transition: "width 600ms ease",
          }}
        />
      </div>
    </div>
  );
}

/* ---------- message components ---------- */
function UserBubble({ content }) {
  return (
    <div className="bmai-rise" style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
      <div
        style={{
          maxWidth: "72%",
          padding: "12px 18px",
          borderRadius: "20px 20px 6px 20px",
          background: "var(--forest)",
          color: "var(--paper)",
          fontSize: 14.5,
          lineHeight: 1.55,
          boxShadow: "var(--shadow-soft)",
          whiteSpace: "pre-wrap",
        }}
      >
        {content}
      </div>
    </div>
  );
}

function AssistantCard({ content, meta, isLast }) {
  return (
    <div className="bmai-rise" style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          background: "var(--forest)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          marginTop: 4,
        }}
      >
        <Logo size={18} tone="light" />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: 0.5,
            color: "var(--ink-muted)",
            textTransform: "uppercase",
            fontWeight: 600,
            marginBottom: 8,
          }}
        >
          BridgeMedAI
          {meta?.intent && (
            <span
              style={{
                marginLeft: 10,
                padding: "2px 8px",
                borderRadius: "var(--r-pill)",
                background: "rgba(31,59,46,0.08)",
                color: "var(--forest)",
                fontSize: 10,
                letterSpacing: 0.4,
              }}
            >
              {intentLabel(meta.intent)}
            </span>
          )}
        </div>

        <div
          style={{
            background: "var(--paper)",
            border: "1px solid var(--cream-edge)",
            borderRadius: "6px 20px 20px 20px",
            padding: "20px 22px",
            boxShadow: "var(--shadow-card)",
          }}
        >
          <AnswerRenderer text={content} />
          {isLast && meta && (
            <SourcesChecklist
              retrieved={meta.retrieved_sources || []}
              generation={meta.generation_sources || []}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          background: "var(--forest)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          marginTop: 4,
        }}
      >
        <Logo size={18} tone="light" />
      </div>
      <div
        style={{
          background: "var(--paper)",
          border: "1px solid var(--cream-edge)",
          borderRadius: "6px 20px 20px 20px",
          padding: "16px 20px",
          color: "var(--ink-muted)",
          fontSize: 14,
          fontStyle: "italic",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <span>A consultar o corpus normativo</span>
        <span style={{ color: "var(--forest)", display: "inline-flex" }}>
          <span className="bmai-dot" />
          <span className="bmai-dot" />
          <span className="bmai-dot" />
        </span>
      </div>
    </div>
  );
}

/* ---------- empty state ---------- */
function EmptyState({ onPick }) {
  return (
    <div
      className="bmai-fade-in"
      style={{
        /* fill the scroll area but can grow taller */
        minHeight: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "16px 32px 28px",
        maxWidth: 800,
        margin: "0 auto",
        width: "100%",
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "4px 12px 4px 6px",
          background: "rgba(31,59,46,0.08)",
          borderRadius: "var(--r-pill)",
          fontSize: 12,
          color: "var(--forest)",
          marginBottom: 16,
        }}
      >
        <Sparkles size={13} />
        Assistente de conformidade regulatória
      </div>

      <h1
        style={{
          /* smaller clamp so it never overflows on typical 1280-1440 laptops */
          fontSize: "clamp(28px, 3.8vw, 52px)",
          fontWeight: 300,
          lineHeight: 1.05,
          letterSpacing: "-0.03em",
          fontVariationSettings: '"opsz" 144, "SOFT" 20',
          marginBottom: 12,
        }}
      >
        Do dispositivo
        <br />
        <span
          style={{
            fontStyle: "italic",
            color: "var(--forest)",
            fontVariationSettings: '"opsz" 144, "SOFT" 100',
            fontWeight: 400,
          }}
        >
          à conformidade.
        </span>
      </h1>

      <p
        style={{
          fontSize: 14.5,
          lineHeight: 1.6,
          color: "var(--ink-muted)",
          maxWidth: 520,
          marginBottom: 24,
        }}
      >
        Coloca uma pergunta sobre MDR, AI Act, classificação de risco, documentação
        técnica ou procedimentos de conformidade. A resposta vem sempre fundamentada
        com as fontes normativas consultadas.
      </p>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
          gap: 10,
          width: "100%",
        }}
        className="bmai-stagger"
      >
        {SUGGESTIONS.map((s) => {
          const Icon = s.icon;
          return (
            <button
              key={s.title}
              onClick={() => onPick(s.q)}
              className="bmai-pressable"
              style={{
                textAlign: "left",
                background: "var(--paper)",
                border: "1px solid var(--cream-edge)",
                borderRadius: "var(--r-lg)",
                padding: "14px 16px",
                cursor: "pointer",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  background: "rgba(31,59,46,0.1)",
                  color: "var(--forest)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <Icon size={15} />
              </div>
              <div
                style={{
                  fontFamily: "var(--display)",
                  fontSize: 15,
                  fontWeight: 500,
                  color: "var(--ink)",
                }}
              >
                {s.title}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--ink-muted)", lineHeight: 1.45 }}>
                {s.q}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- details panel ---------- */
function DetailsPanel({ meta, collapsed, onToggle }) {
  if (collapsed) {
    return (
      <aside
        style={{
          width: 44,
          background: "var(--paper)",
          border: "1px solid var(--cream-edge)",
          borderRadius: "var(--r-lg)",
          padding: 10,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          height: "100%",
        }}
      >
        <button
          onClick={onToggle}
          title="Expandir detalhes"
          className="bmai-pressable"
          style={{
            border: "none",
            background: "transparent",
            cursor: "pointer",
            color: "var(--ink-muted)",
            padding: 4,
          }}
        >
          <ChevronRight size={18} />
        </button>
        <div
          style={{
            writingMode: "vertical-rl",
            transform: "rotate(180deg)",
            fontSize: 11,
            letterSpacing: 2,
            textTransform: "uppercase",
            color: "var(--ink-muted)",
            fontWeight: 600,
          }}
        >
          Detalhes
        </div>
      </aside>
    );
  }

  const retrieved = meta?.retrieved_sources || [];
  const generation = meta?.generation_sources || [];

  return (
    <aside
      style={{
        width: 340,
        background: "var(--paper)",
        border: "1px solid var(--cream-edge)",
        borderRadius: "var(--r-lg)",
        padding: "18px 18px 22px",
        overflowY: "auto",
        height: "100%",
        minHeight: 0,
        position: "relative",
      }}
      className="bmai-noise"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <h3
          style={{
            fontFamily: "var(--display)",
            fontSize: 18,
            margin: 0,
            color: "var(--ink)",
          }}
        >
          Detalhes da resposta
        </h3>
        <button
          onClick={onToggle}
          title="Recolher"
          className="bmai-pressable"
          style={{
            border: "none",
            background: "transparent",
            cursor: "pointer",
            color: "var(--ink-faded)",
            padding: 4,
          }}
        >
          <ChevronDown size={16} style={{ transform: "rotate(-90deg)" }} />
        </button>
      </div>

      <Field label="Intenção detetada">
        {meta?.intent ? (
          <StatusPill tone="forest">{intentLabel(meta.intent)}</StatusPill>
        ) : (
          <Muted>Sem intent ainda</Muted>
        )}
      </Field>

      <Field label="Documentos-alvo">
        {meta?.target_docs?.length ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {meta.target_docs.map((d) => (
              <StatusPill key={d} tone="info">
                {docLabel(d)}
              </StatusPill>
            ))}
          </div>
        ) : (
          <Muted>Sem documentos identificados</Muted>
        )}
      </Field>

      <Divider />

      <CollapsibleList
        title="Fontes utilizadas na geração"
        icon={<FileText size={14} />}
        items={generation}
        emptyLabel="Ainda não há fontes usadas na geração."
        tone="check"
      />

      <Divider />

      <CollapsibleList
        title="Fontes recuperadas"
        icon={<ListChecks size={14} />}
        items={retrieved}
        emptyLabel="Ainda não há fontes recuperadas."
        tone="neutral"
      />
    </aside>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          fontSize: 11,
          letterSpacing: 0.5,
          textTransform: "uppercase",
          color: "var(--ink-muted)",
          fontWeight: 600,
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function Muted({ children }) {
  return (
    <span style={{ color: "var(--ink-faded)", fontSize: 13 }}>{children}</span>
  );
}

function Divider() {
  return (
    <div
      style={{
        height: 1,
        background: "rgba(21,42,32,0.08)",
        margin: "14px -18px 16px",
      }}
    />
  );
}

function CollapsibleList({ title, icon, items, emptyLabel, tone = "neutral" }) {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          border: "none",
          background: "transparent",
          padding: 0,
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 10,
          color: "var(--ink)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 600, fontSize: 13 }}>
          {icon}
          {title}
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 11,
              color: "var(--ink-faded)",
              marginLeft: 4,
            }}
          >
            {items.length}
          </span>
        </span>
        {open ? (
          <ChevronDown size={14} color="var(--ink-faded)" />
        ) : (
          <ChevronRight size={14} color="var(--ink-faded)" />
        )}
      </button>

      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {items.length === 0 ? (
            <Muted>{emptyLabel}</Muted>
          ) : (
            items.map((s, i) => (
              <div
                key={`${s.citation_label}-${i}`}
                style={{
                  border: "1px solid var(--cream-edge)",
                  borderRadius: 12,
                  padding: "10px 12px",
                  background: "rgba(239,233,212,0.5)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    marginBottom: 6,
                    flexWrap: "wrap",
                  }}
                >
                  <StatusPill tone={tone}>
                    {docLabel(s.short_name)}
                  </StatusPill>
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 11,
                      color: "var(--ink-muted)",
                    }}
                  >
                    {s.section_number}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 500,
                    color: "var(--ink)",
                    lineHeight: 1.35,
                  }}
                >
                  {s.section_title || s.citation_label}
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginTop: 6,
                    fontSize: 11,
                    color: "var(--ink-faded)",
                    fontFamily: "var(--mono)",
                  }}
                >
                  <span>
                    pp. {s.page_start ?? "—"}
                    {s.page_end && s.page_end !== s.page_start ? `–${s.page_end}` : ""}
                  </span>
                  <span>{Number(s.score_adjusted || 0).toFixed(3)}</span>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- regulatory flow components ---------- */
function RegulatoryStepIndicator({ step }) {
  const current = regulatoryStepIndex(step);
  const steps = [
    { key: "analysis", label: "Análise regulatória", idx: 0 },
    { key: "collect", label: "Recolha de informação", idx: 1 },
    { key: "document", label: "Documento PMCF", idx: 2 },
  ];
  return (
    <section
      className="bmai-stagger"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 0,
        padding: "12px 16px",
        background: "var(--paper)",
        border: "1px solid var(--cream-edge)",
        borderRadius: "var(--r-lg)",
        marginTop: 6,
      }}
    >
      {steps.map((s, i) => {
        const done = current > s.idx;
        const active = Math.floor(current) === s.idx || (current === 0.5 && s.idx === 0);
        const color = done
          ? "var(--check)"
          : active
          ? "var(--forest)"
          : "var(--ink-faded)";
        return (
          <React.Fragment key={s.key}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                flex: "0 0 auto",
              }}
            >
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background:
                    done || active
                      ? color
                      : "rgba(21,42,32,0.08)",
                  color: done || active ? "var(--paper)" : "var(--ink-muted)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "var(--mono)",
                  fontSize: 12,
                  fontWeight: 600,
                  transition: "all 240ms ease",
                }}
              >
                {done ? <Check size={14} strokeWidth={3} /> : s.idx + 1}
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: active ? "var(--ink)" : done ? "var(--ink-muted)" : "var(--ink-faded)",
                  fontWeight: active ? 600 : 500,
                  letterSpacing: 0.2,
                }}
              >
                {s.label}
              </div>
            </div>
            {i < steps.length - 1 && (
              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: current > s.idx
                    ? "var(--check)"
                    : "rgba(21,42,32,0.12)",
                  margin: "0 14px",
                  transition: "background 240ms ease",
                }}
              />
            )}
          </React.Fragment>
        );
      })}
    </section>
  );
}

function RegulatoryEmptyState({ customTemplateName, onUploadTemplate }) {
  const fileInputRef = useRef(null);
  return (
    <div
      className="bmai-fade-in"
      style={{
        minHeight: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "16px 32px 28px",
        maxWidth: 760,
        margin: "0 auto",
        width: "100%",
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "4px 12px 4px 6px",
          background: "rgba(31,59,46,0.08)",
          borderRadius: "var(--r-pill)",
          fontSize: 12,
          color: "var(--forest)",
          marginBottom: 16,
        }}
      >
        <Stethoscope size={13} />
        Análise guiada de dispositivo + preenchimento PMCF
      </div>

      <h1
        style={{
          fontSize: "clamp(28px, 3.8vw, 52px)",
          fontWeight: 300,
          lineHeight: 1.05,
          letterSpacing: "-0.03em",
          fontVariationSettings: '"opsz" 144, "SOFT" 20',
          marginBottom: 12,
        }}
      >
        Descreve o teu
        <br />
        <span
          style={{
            fontStyle: "italic",
            color: "var(--forest)",
            fontVariationSettings: '"opsz" 144, "SOFT" 100',
            fontWeight: 400,
          }}
        >
          dispositivo médico.
        </span>
      </h1>

      <p
        style={{
          fontSize: 14.5,
          lineHeight: 1.6,
          color: "var(--ink-muted)",
          maxWidth: 560,
          marginBottom: 20,
        }}
      >
        Em três passos: <strong>análise regulatória</strong> (classe MDR, AI Act, normas aplicáveis),
        <strong> recolha da informação em falta</strong> e <strong>preenchimento automático do Plano PMCF</strong>.
        Campos sensíveis ou em falta ficam sinalizados para revisão manual no documento.
      </p>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 14px",
          background: "var(--paper)",
          border: "1px solid var(--cream-edge)",
          borderRadius: "var(--r-md)",
          fontSize: 13,
          marginBottom: 16,
          width: "100%",
          maxWidth: 560,
        }}
      >
        <FileText size={15} color="var(--forest)" />
        <div style={{ flex: 1 }}>
          <div style={{ color: "var(--ink)", fontWeight: 500 }}>
            {customTemplateName
              ? `Template: ${customTemplateName}`
              : "Template: TMP-CE-05 Post-Market Clinical Follow-Up Plan (pré-carregado)"}
          </div>
          <div style={{ color: "var(--ink-faded)", fontSize: 11, marginTop: 2 }}>
            {customTemplateName
              ? "Template personalizado será usado ao gerar o documento."
              : "Podes substituir por um .docx próprio antes de começar."}
          </div>
        </div>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="bmai-pressable"
          style={{
            border: "1px solid var(--cream-edge)",
            background: "var(--cream)",
            color: "var(--forest)",
            padding: "6px 12px",
            borderRadius: "var(--r-pill)",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Upload size={12} />
          {customTemplateName ? "Substituir" : "Carregar .docx"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".docx"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUploadTemplate(f);
            e.target.value = "";
          }}
        />
      </div>

      <p style={{ fontSize: 12.5, color: "var(--ink-faded)", marginBottom: 0 }}>
        Exemplo: <em>“Termómetro digital de testa com sensor de infravermelhos e algoritmo de IA
        que estima a temperatura central a partir da leitura periférica, para utilização em contexto
        clínico por profissionais de saúde.”</em>
      </p>
    </div>
  );
}

function RegulatoryActionBar({ pendingAction, loading, onConfirm, onFinalize, onDownload, downloadName, filledCount, flaggedCount }) {
  if (pendingAction === "confirm_fill_pmcf") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "12px 16px",
          background: "rgba(31,59,46,0.06)",
          border: "1px solid rgba(31,59,46,0.18)",
          borderRadius: "var(--r-lg)",
          maxWidth: 860,
          width: "100%",
          alignSelf: "center",
          boxSizing: "border-box",
          marginTop: 8,
        }}
      >
        <ClipboardCheck size={16} color="var(--forest)" />
        <span style={{ flex: 1, fontSize: 13.5, color: "var(--ink)" }}>
          Queres que preencha o Plano PMCF com base nesta análise?
        </span>
        <button
          disabled={loading}
          onClick={() => onConfirm(false)}
          className="bmai-pressable"
          style={{
            border: "1px solid var(--cream-edge)",
            background: "var(--paper)",
            color: "var(--ink-muted)",
            padding: "8px 14px",
            borderRadius: "var(--r-pill)",
            fontSize: 13,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          Agora não
        </button>
        <button
          disabled={loading}
          onClick={() => onConfirm(true)}
          className="bmai-pressable"
          style={{
            border: "none",
            background: "var(--forest)",
            color: "var(--paper)",
            padding: "8px 16px",
            borderRadius: "var(--r-pill)",
            fontSize: 13,
            fontWeight: 600,
            cursor: loading ? "not-allowed" : "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <FileText size={14} />
          Sim, preencher PMCF
        </button>
      </div>
    );
  }

  if (pendingAction === "answer_missing_info") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 14px",
          background: "rgba(184,117,58,0.06)",
          border: "1px dashed rgba(184,117,58,0.30)",
          borderRadius: "var(--r-md)",
          maxWidth: 860,
          width: "100%",
          alignSelf: "center",
          boxSizing: "border-box",
          marginTop: 6,
        }}
      >
        <AlertCircle size={15} color="var(--pending)" />
        <span style={{ flex: 1, fontSize: 12.5, color: "var(--ink-muted)" }}>
          Podes responder só ao que souberes. Campos em branco ficam como <em>"⚠️ Preencher manualmente"</em>.
        </span>
        <button
          disabled={loading}
          onClick={onFinalize}
          className="bmai-pressable"
          style={{
            border: "1px solid rgba(184,117,58,0.4)",
            background: "transparent",
            color: "var(--pending)",
            padding: "6px 12px",
            borderRadius: "var(--r-pill)",
            fontSize: 12,
            fontWeight: 500,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          Gerar com o que há
        </button>
      </div>
    );
  }

  if (pendingAction === "download_document") {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "14px 18px",
          background: "var(--forest)",
          color: "var(--paper)",
          borderRadius: "var(--r-lg)",
          maxWidth: 860,
          width: "100%",
          alignSelf: "center",
          boxSizing: "border-box",
          marginTop: 8,
          boxShadow: "var(--shadow-card)",
        }}
      >
        <CheckCircle2 size={22} color="#cdddc0" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>
            Documento PMCF pronto
          </div>
          <div style={{ fontSize: 12, opacity: 0.85, fontFamily: "var(--mono)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {filledCount} preenchidos · {flaggedCount} para revisão manual · {downloadName}
          </div>
        </div>
        <button
          onClick={onDownload}
          className="bmai-pressable"
          style={{
            border: "none",
            background: "var(--cream)",
            color: "var(--forest)",
            padding: "10px 18px",
            borderRadius: "var(--r-pill)",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            flexShrink: 0,
          }}
        >
          <Download size={15} strokeWidth={2.4} />
          Descarregar PMCF
        </button>
      </div>
    );
  }

  return null;
}

/* ---------- app shell ---------- */
export default function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [showApiConfig, setShowApiConfig] = useState(false);
  const [input, setInput] = useState("");
  const [health, setHealth] = useState({ state: "idle", data: null, error: "" });
  const [chatState, setChatState] = useState({ loading: false, error: "" });
  const [detailsCollapsed, setDetailsCollapsed] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const [conversations, setConversations] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (!saved) return [createConversation("Nova conversa")];
      const parsed = JSON.parse(saved);
      if (!Array.isArray(parsed.conversations) || parsed.conversations.length === 0) {
        return [createConversation("Nova conversa")];
      }
      return parsed.conversations;
    } catch {
      return [createConversation("Nova conversa")];
    }
  });

  const [activeConversationId, setActiveConversationId] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (!saved) return null;
      const parsed = JSON.parse(saved);
      return parsed.activeConversationId || null;
    } catch {
      return null;
    }
  });

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const normalizedBaseUrl = useMemo(
    () => apiBaseUrl.trim().replace(/\/$/, ""),
    [apiBaseUrl]
  );

  const activeConversation =
    conversations.find((c) => c.id === activeConversationId) || conversations[0];

  useEffect(() => {
    if (!activeConversationId && conversations.length > 0) {
      setActiveConversationId(conversations[0].id);
    }
  }, [activeConversationId, conversations]);

  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ conversations, activeConversationId })
      );
    } catch {
      /* ignore */
    }
  }, [conversations, activeConversationId]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [activeConversation?.messages, chatState.loading]);

  async function callApi(path, options = {}) {
    const response = await fetch(`${normalizedBaseUrl}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      const detail =
        typeof payload === "object" && payload?.detail
          ? payload.detail
          : typeof payload === "string"
          ? payload
          : "Pedido falhou.";
      throw new Error(String(detail));
    }
    return payload;
  }

  async function checkHealth() {
    setHealth({ state: "loading", data: null, error: "" });
    try {
      const data = await callApi("/health", { method: "GET" });
      setHealth({ state: "ok", data, error: "" });
    } catch (error) {
      setHealth({ state: "error", data: null, error: error.message || "Erro de ligação." });
    }
  }

  function handleNewConversation() {
    const nc = createConversation("Nova conversa");
    setConversations((prev) => [nc, ...prev]);
    setActiveConversationId(nc.id);
    setInput("");
    setChatState({ loading: false, error: "" });
    inputRef.current?.focus();
  }

  function handleNewRegulatoryConversation() {
    const nc = createConversation("Análise de dispositivo", "regulatory");
    setConversations((prev) => [nc, ...prev]);
    setActiveConversationId(nc.id);
    setInput("");
    setChatState({ loading: false, error: "" });
    inputRef.current?.focus();
  }

  function updateActiveConversation(patch) {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeConversation?.id
          ? {
              ...c,
              ...patch,
              updatedAt: new Date().toISOString(),
            }
          : c
      )
    );
  }

  function appendMessage(message, patch = {}) {
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeConversation?.id
          ? {
              ...c,
              ...patch,
              messages: [...c.messages, message],
              updatedAt: new Date().toISOString(),
            }
          : c
      )
    );
  }

  async function handleUploadTemplate(file) {
    if (!file || !activeConversation || activeConversation.mode !== "regulatory") return;
    setChatState({ loading: true, error: "" });
    try {
      let sessionId = activeConversation.regulatory?.sessionId;
      if (!sessionId) {
        sessionId = crypto.randomUUID();
      }
      const fd = new FormData();
      fd.append("file", file);
      const response = await fetch(
        `${normalizedBaseUrl}/regulatory/upload-template?session_id=${encodeURIComponent(sessionId)}`,
        { method: "POST", body: fd }
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "Erro ao carregar template.");
      updateActiveConversation({
        regulatory: {
          ...(activeConversation.regulatory || {}),
          sessionId: data.session_id,
          customTemplateName: data.template_name,
        },
      });
      appendMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Template personalizado carregado: \`${data.template_name}\`. Podes agora descrever o dispositivo.`,
      });
      setChatState({ loading: false, error: "" });
    } catch (error) {
      setChatState({ loading: false, error: error.message || "Erro ao carregar template." });
    }
  }

  async function handleRegulatoryConfirm(accept) {
    const sessionId = activeConversation?.regulatory?.sessionId;
    if (!sessionId) return;
    setChatState({ loading: true, error: "" });
    try {
      const data = await callApi("/regulatory/confirm", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, accept }),
      });
      appendMessage(
        {
          id: crypto.randomUUID(),
          role: "user",
          content: accept ? "Sim, por favor preenche o PMCF." : "Não, obrigado.",
        },
      );
      appendMessage(
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.assistant_text,
          regulatoryPayload: data,
        },
        {
          regulatory: {
            ...(activeConversation.regulatory || {}),
            step: data.step,
            pendingAction: data.pending_action,
            filledFields: data.filled_fields || activeConversation.regulatory?.filledFields || [],
            flaggedFields: data.flagged_fields || activeConversation.regulatory?.flaggedFields || [],
            downloadUrl: data.download_url || activeConversation.regulatory?.downloadUrl || null,
            downloadName: data.download_name || activeConversation.regulatory?.downloadName || null,
          },
        }
      );
      setChatState({ loading: false, error: "" });
    } catch (error) {
      setChatState({ loading: false, error: error.message || "Erro na confirmação." });
    }
  }

  async function handleRegulatoryFinalize() {
    const sessionId = activeConversation?.regulatory?.sessionId;
    if (!sessionId) return;
    setChatState({ loading: true, error: "" });
    try {
      const data = await callApi("/regulatory/finalize", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, accept: true }),
      });
      appendMessage(
        {
          id: crypto.randomUUID(),
          role: "user",
          content: "Gera o documento com os campos em falta sinalizados.",
        },
      );
      appendMessage(
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.assistant_text,
          regulatoryPayload: data,
        },
        {
          regulatory: {
            ...(activeConversation.regulatory || {}),
            step: data.step,
            pendingAction: data.pending_action,
            filledFields: data.filled_fields || [],
            flaggedFields: data.flagged_fields || [],
            downloadUrl: data.download_url || null,
            downloadName: data.download_name || null,
          },
        }
      );
      setChatState({ loading: false, error: "" });
    } catch (error) {
      setChatState({ loading: false, error: error.message || "Erro na finalização." });
    }
  }

  function handleDeleteConversation(event, conversationId) {
    event.stopPropagation();
    const confirmed = window.confirm("Queres mesmo apagar esta conversa?");
    if (!confirmed) return;
    setConversations((prev) => {
      const filtered = prev.filter((c) => c.id !== conversationId);
      if (filtered.length === 0) {
        const fallback = createConversation("Nova conversa");
        setActiveConversationId(fallback.id);
        return [fallback];
      }
      if (conversationId === activeConversationId) {
        setActiveConversationId(filtered[0].id);
      }
      return filtered;
    });
  }

  async function sendMessage(maybeText) {
    const question = (maybeText ?? input).trim();
    if (!question || !activeConversation || chatState.loading) return;

    if (activeConversation.mode === "regulatory") {
      await sendRegulatoryMessage(question);
      return;
    }

    setChatState({ loading: true, error: "" });
    const userMessage = { id: crypto.randomUUID(), role: "user", content: question };

    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeConversation.id
          ? {
              ...c,
              title: c.messages.length === 0 ? formatConversationTitle(question) : c.title,
              messages: [...c.messages, userMessage],
              updatedAt: new Date().toISOString(),
            }
          : c
      )
    );

    setInput("");

    try {
      const data = await callApi("/chat", {
        method: "POST",
        body: JSON.stringify({ question }),
      });
      const assistantMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.answer || "Sem resposta devolvida pelo backend.",
        meta: {
          intent: data.intent || null,
          target_docs: data.target_docs || [],
          retrieved_sources: data.retrieved_sources || [],
          generation_sources: data.generation_sources || [],
        },
      };

      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeConversation.id
            ? {
                ...c,
                messages: [...c.messages, assistantMessage],
                meta: assistantMessage.meta,
                updatedAt: new Date().toISOString(),
              }
            : c
        )
      );
      setChatState({ loading: false, error: "" });
    } catch (error) {
      setChatState({ loading: false, error: error.message || "Erro no endpoint /chat." });
    }
  }

  async function sendRegulatoryMessage(text) {
    setChatState({ loading: true, error: "" });
    const regulatory = activeConversation.regulatory || {};
    const step = regulatory.step || "awaiting_description";

    const userMessage = { id: crypto.randomUUID(), role: "user", content: text };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeConversation.id
          ? {
              ...c,
              title: c.messages.length === 0 ? formatConversationTitle(text) : c.title,
              messages: [...c.messages, userMessage],
              updatedAt: new Date().toISOString(),
            }
          : c
      )
    );
    setInput("");

    try {
      let data;
      if (step === "awaiting_description") {
        data = await callApi("/regulatory/start", {
          method: "POST",
          body: JSON.stringify({
            description: text,
            session_id: regulatory.sessionId || null,
          }),
        });
      } else if (step === "collecting_info") {
        data = await callApi("/regulatory/message", {
          method: "POST",
          body: JSON.stringify({
            session_id: regulatory.sessionId,
            message: text,
          }),
        });
      } else {
        throw new Error("Este passo não aceita mais mensagens livres. Usa os botões disponíveis.");
      }

      const assistantMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.assistant_text,
        regulatoryPayload: data,
      };

      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeConversation.id
            ? {
                ...c,
                messages: [...c.messages, assistantMessage],
                regulatory: {
                  ...(c.regulatory || {}),
                  sessionId: data.session_id,
                  step: data.step,
                  pendingAction: data.pending_action,
                  lastAnalysis: data.analysis || c.regulatory?.lastAnalysis || null,
                  filledFields: data.filled_fields || c.regulatory?.filledFields || [],
                  flaggedFields: data.flagged_fields || c.regulatory?.flaggedFields || [],
                  downloadUrl: data.download_url || c.regulatory?.downloadUrl || null,
                  downloadName: data.download_name || c.regulatory?.downloadName || null,
                },
                updatedAt: new Date().toISOString(),
              }
            : c
        )
      );
      setChatState({ loading: false, error: "" });
    } catch (error) {
      setChatState({ loading: false, error: error.message || "Erro no fluxo regulatório." });
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  const currentMeta = activeConversation?.meta || null;
  const messages = activeConversation?.messages || [];
  const isEmpty = messages.length === 0 && !chatState.loading;

  return (
    <div
      style={{
        height: "100dvh",
        display: "grid",
        gridTemplateColumns: `${sidebarCollapsed ? 64 : 268}px 1fr`,
        gap: 0,
        overflow: "hidden",
        transition: "grid-template-columns 260ms cubic-bezier(0.4, 0, 0.2, 1)",
      }}
    >
      {/* SIDEBAR */}
      <aside
        style={{
          background: "var(--forest)",
          color: "var(--paper)",
          padding: sidebarCollapsed ? "18px 10px" : "20px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 14,
          height: "100%",
          minHeight: 0,
          position: "relative",
          overflow: "hidden",
        }}
        className="bmai-noise"
      >
        {/* subtle top-right ornament */}
        <div
          aria-hidden
          style={{
            position: "absolute",
            top: -60,
            right: -60,
            width: 180,
            height: 180,
            borderRadius: "50%",
            background: "radial-gradient(closest-side, rgba(205,221,192,0.16), transparent)",
            pointerEvents: "none",
          }}
        />

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <Logo size={18} tone="light" />
            {!sidebarCollapsed && (
              <div style={{ minWidth: 0 }}>
                <div
                  style={{
                    fontFamily: "var(--display)",
                    fontSize: 17,
                    fontWeight: 500,
                    letterSpacing: "-0.01em",
                    lineHeight: 1.1,
                  }}
                >
                  BridgeMed<span style={{ fontStyle: "italic" }}>AI</span>
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "rgba(239,233,212,0.6)",
                    letterSpacing: 0.3,
                    textTransform: "uppercase",
                    marginTop: 2,
                  }}
                >
                  Compliance assistant
                </div>
              </div>
            )}
          </div>
          <button
            onClick={() => setSidebarCollapsed((v) => !v)}
            className="bmai-pressable"
            title={sidebarCollapsed ? "Expandir" : "Recolher"}
            style={{
              border: "none",
              background: "rgba(239,233,212,0.06)",
              color: "var(--paper)",
              width: 30,
              height: 30,
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <Menu size={15} />
          </button>
        </div>

        <button
          onClick={handleNewConversation}
          className="bmai-pressable"
          title="Nova conversa"
          style={{
            background: "var(--cream)",
            color: "var(--forest)",
            border: "none",
            borderRadius: 14,
            padding: sidebarCollapsed ? "12px 0" : "12px 14px",
            display: "flex",
            alignItems: "center",
            justifyContent: sidebarCollapsed ? "center" : "flex-start",
            gap: 10,
            fontWeight: 600,
            fontSize: 14,
            cursor: "pointer",
            fontFamily: "var(--body)",
          }}
        >
          <Plus size={16} strokeWidth={2.5} />
          {!sidebarCollapsed && "Nova conversa"}
        </button>

        <button
          onClick={handleNewRegulatoryConversation}
          className="bmai-pressable"
          title="Analisar dispositivo e preencher PMCF"
          style={{
            background: "rgba(239,233,212,0.08)",
            color: "var(--paper)",
            border: "1px solid rgba(239,233,212,0.18)",
            borderRadius: 14,
            padding: sidebarCollapsed ? "10px 0" : "10px 14px",
            display: "flex",
            alignItems: "center",
            justifyContent: sidebarCollapsed ? "center" : "flex-start",
            gap: 10,
            fontWeight: 500,
            fontSize: 13,
            cursor: "pointer",
            fontFamily: "var(--body)",
          }}
        >
          <Stethoscope size={15} />
          {!sidebarCollapsed && "Analisar dispositivo"}
        </button>

        {!sidebarCollapsed && (
          <>
            <div
              style={{
                fontSize: 10,
                letterSpacing: 1.4,
                color: "rgba(239,233,212,0.55)",
                textTransform: "uppercase",
                marginTop: 8,
                fontWeight: 600,
              }}
            >
              Histórico
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                overflowY: "auto",
                minHeight: 0,
                margin: "0 -6px",
                padding: "0 6px",
              }}
            >
              {conversations.map((c) => {
                const isActive = c.id === activeConversation?.id;
                return (
                  <div
                    key={c.id}
                    onClick={() => setActiveConversationId(c.id)}
                    className="bmai-pressable"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "10px 12px",
                      borderRadius: 12,
                      background: isActive ? "rgba(239,233,212,0.12)" : "transparent",
                      color: isActive ? "var(--paper)" : "rgba(239,233,212,0.75)",
                      cursor: "pointer",
                      border: `1px solid ${
                        isActive ? "rgba(239,233,212,0.18)" : "transparent"
                      }`,
                    }}
                  >
                    {c.mode === "regulatory" ? (
                      <Stethoscope size={14} style={{ flexShrink: 0, opacity: 0.8 }} />
                    ) : (
                      <MessageSquare size={14} style={{ flexShrink: 0, opacity: 0.8 }} />
                    )}
                    <span
                      style={{
                        flex: 1,
                        fontSize: 13,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {c.title}
                    </span>
                    <button
                      onClick={(e) => handleDeleteConversation(e, c.id)}
                      title="Apagar"
                      style={{
                        border: "none",
                        background: "transparent",
                        color: "rgba(239,233,212,0.45)",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        padding: 2,
                        borderRadius: 4,
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                );
              })}
            </div>

            {/* footer */}
            <div
              style={{
                marginTop: "auto",
                paddingTop: 14,
                borderTop: "1px solid rgba(239,233,212,0.08)",
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                }}
              >
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 11,
                    color: "rgba(239,233,212,0.7)",
                  }}
                >
                  <Dot
                    color={
                      health.state === "ok"
                        ? "#92d194"
                        : health.state === "error"
                        ? "#e39393"
                        : health.state === "loading"
                        ? "#e6c089"
                        : "rgba(239,233,212,0.4)"
                    }
                  />
                  {health.state === "ok"
                    ? "Backend online"
                    : health.state === "error"
                    ? "Sem ligação"
                    : health.state === "loading"
                    ? "A verificar..."
                    : "Estado desconhecido"}
                </div>
                <button
                  onClick={checkHealth}
                  title="Testar ligação"
                  className="bmai-pressable"
                  style={{
                    border: "1px solid rgba(239,233,212,0.14)",
                    background: "transparent",
                    color: "var(--paper)",
                    padding: "4px 10px",
                    borderRadius: "var(--r-pill)",
                    cursor: "pointer",
                    fontSize: 11,
                  }}
                >
                  testar
                </button>
              </div>
              <button
                onClick={() => setShowApiConfig((v) => !v)}
                style={{
                  border: "none",
                  background: "transparent",
                  color: "rgba(239,233,212,0.55)",
                  fontSize: 11,
                  textAlign: "left",
                  padding: 0,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                }}
              >
                {showApiConfig ? "Ocultar" : "Configurar"} endpoint
                <ChevronDown
                  size={11}
                  style={{
                    transform: showApiConfig ? "rotate(-180deg)" : "rotate(0deg)",
                    transition: "transform 200ms",
                  }}
                />
              </button>
              {showApiConfig && (
                <input
                  value={apiBaseUrl}
                  onChange={(e) => setApiBaseUrl(e.target.value)}
                  placeholder="http://127.0.0.1:8000"
                  style={{
                    background: "rgba(239,233,212,0.06)",
                    border: "1px solid rgba(239,233,212,0.14)",
                    borderRadius: 8,
                    padding: "8px 10px",
                    fontSize: 12,
                    color: "var(--paper)",
                    outline: "none",
                    fontFamily: "var(--mono)",
                  }}
                />
              )}
            </div>
          </>
        )}
      </aside>

      {/* MAIN */}
      <main
        style={{
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          height: "100%",
          padding: "18px 22px 22px",
          gap: 14,
          overflow: "hidden",
        }}
      >
        {/* topbar */}
        <header
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 20,
            flexShrink: 0,
          }}
        >
          <div>
            <div
              style={{
                fontSize: 11,
                letterSpacing: 1.4,
                textTransform: "uppercase",
                color: "var(--ink-muted)",
                fontWeight: 600,
                marginBottom: 4,
              }}
            >
              {activeConversation?.title && activeConversation.messages.length > 0
                ? "Sessão atual"
                : "Nova sessão"}
            </div>
            <h1
              style={{
                fontFamily: "var(--display)",
                fontSize: 26,
                lineHeight: 1.1,
                color: "var(--ink)",
                margin: 0,
                fontWeight: 400,
                letterSpacing: "-0.015em",
                fontVariationSettings: '"opsz" 72, "SOFT" 40',
                maxWidth: 680,
              }}
            >
              {activeConversation?.title && activeConversation.messages.length > 0 ? (
                <span>
                  {activeConversation.title}
                </span>
              ) : (
                <>
                  Framework integrado de{" "}
                  <span style={{ fontStyle: "italic", color: "var(--forest)" }}>
                    conformidade regulatória
                  </span>{" "}
                  para dispositivos médicos com IA.
                </>
              )}
            </h1>
          </div>

          <HealthIndicator state={health.state} />
        </header>

        {/* KPI bar (apenas modo RAG) */}
        {activeConversation?.mode !== "regulatory" && currentMeta && messages.length > 0 && (
          <KpiBar meta={currentMeta} />
        )}

        {/* Step indicator (apenas modo regulatório) */}
        {activeConversation?.mode === "regulatory" && (
          <RegulatoryStepIndicator step={activeConversation.regulatory?.step || "awaiting_description"} />
        )}

        {/* alerts */}
        {chatState.error && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 14px",
              borderRadius: "var(--r-md)",
              background: "rgba(162,45,45,0.08)",
              color: "var(--missing)",
              border: "1px solid rgba(162,45,45,0.24)",
              fontSize: 13,
              flexShrink: 0,
            }}
          >
            <AlertCircle size={15} />
            <span>{chatState.error}</span>
          </div>
        )}
        {health.state === "error" && health.error && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 14px",
              borderRadius: "var(--r-md)",
              background: "rgba(184,117,58,0.08)",
              color: "var(--pending)",
              border: "1px solid rgba(184,117,58,0.24)",
              fontSize: 13,
              flexShrink: 0,
            }}
          >
            <AlertCircle size={15} />
            <span>{health.error}</span>
          </div>
        )}

        {/* chat + details */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            gap: 14,
            alignItems: "stretch",
          }}
        >
          <section
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              minWidth: 0,
              minHeight: 0,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                flex: 1,
                minHeight: 0,
                overflowY: "auto",
                overflowX: "hidden",
                /* no horizontal bleed — keep padding inside so scrollbar stays at edge */
                padding: isEmpty ? 0 : "6px 4px 20px",
              }}
            >
              {isEmpty ? (
                activeConversation?.mode === "regulatory" ? (
                  <RegulatoryEmptyState
                    customTemplateName={activeConversation.regulatory?.customTemplateName}
                    onUploadTemplate={handleUploadTemplate}
                  />
                ) : (
                  <EmptyState onPick={(q) => sendMessage(q)} />
                )
              ) : (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 22,
                    maxWidth: 860,
                    marginLeft: "auto",
                    marginRight: "auto",
                    width: "100%",
                    boxSizing: "border-box",
                  }}
                >
                  {messages.map((m, idx) => {
                    const isLast = idx === messages.length - 1;
                    return m.role === "user" ? (
                      <UserBubble key={m.id} content={m.content} />
                    ) : (
                      <AssistantCard
                        key={m.id}
                        content={m.content}
                        meta={m.meta}
                        isLast={isLast}
                      />
                    );
                  })}
                  {chatState.loading && <TypingIndicator />}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>

            {/* regulatory action bar */}
            {activeConversation?.mode === "regulatory" && activeConversation.regulatory?.pendingAction && (
              <RegulatoryActionBar
                pendingAction={activeConversation.regulatory.pendingAction}
                loading={chatState.loading}
                onConfirm={handleRegulatoryConfirm}
                onFinalize={handleRegulatoryFinalize}
                onDownload={() => {
                  const url = `${normalizedBaseUrl}/regulatory/download/${activeConversation.regulatory.sessionId}`;
                  window.open(url, "_blank");
                }}
                downloadName={activeConversation.regulatory.downloadName}
                filledCount={(activeConversation.regulatory.filledFields || []).length}
                flaggedCount={(activeConversation.regulatory.flaggedFields || []).length}
              />
            )}

            {/* input area */}
            <div
              style={{
                flexShrink: 0,
                marginTop: 8,
                padding: "12px 14px",
                background: "var(--paper)",
                border: "1px solid var(--cream-edge)",
                borderRadius: "var(--r-lg)",
                boxShadow: "var(--shadow-soft)",
                display: "flex",
                alignItems: "flex-end",
                gap: 10,
                maxWidth: 860,
                width: "100%",
                alignSelf: "center",
                boxSizing: "border-box",
                opacity:
                  activeConversation?.mode === "regulatory" &&
                  activeConversation.regulatory?.step === "document_ready"
                    ? 0.5
                    : 1,
              }}
            >
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                disabled={
                  activeConversation?.mode === "regulatory" &&
                  (activeConversation.regulatory?.step === "awaiting_fill_confirmation" ||
                   activeConversation.regulatory?.step === "document_ready")
                }
                placeholder={
                  activeConversation?.mode === "regulatory"
                    ? (activeConversation.regulatory?.step === "awaiting_description"
                        ? "Descreve o dispositivo: finalidade, utilizadores, modo de utilização, componente de IA..."
                        : activeConversation.regulatory?.step === "collecting_info"
                        ? "Responde às perguntas acima (podes responder só a algumas)..."
                        : activeConversation.regulatory?.step === "awaiting_fill_confirmation"
                        ? "Usa os botões acima para continuar."
                        : "Documento pronto — descarrega acima.")
                    : "Escreve a tua pergunta sobre MDR, AI Act, classificação..."
                }
                style={{
                  flex: 1,
                  border: "none",
                  background: "transparent",
                  resize: "none",
                  outline: "none",
                  fontSize: 15,
                  lineHeight: 1.5,
                  fontFamily: "var(--body)",
                  color: "var(--ink)",
                  padding: "8px 6px",
                  minHeight: 40,
                  maxHeight: 200,
                }}
              />
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  paddingBottom: 4,
                }}
              >
                <span style={{ fontSize: 11, color: "var(--ink-faded)", userSelect: "none" }}>
                  Enter ↵
                </span>
                <button
                  onClick={() => sendMessage()}
                  disabled={chatState.loading || !input.trim()}
                  title="Enviar"
                  className="bmai-pressable"
                  style={{
                    width: 42,
                    height: 42,
                    borderRadius: "50%",
                    border: "none",
                    background:
                      chatState.loading || !input.trim()
                        ? "rgba(31,59,46,0.18)"
                        : "var(--forest)",
                    color: "var(--paper)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    cursor:
                      chatState.loading || !input.trim() ? "not-allowed" : "pointer",
                    flexShrink: 0,
                  }}
                >
                  <Send size={16} strokeWidth={2.2} />
                </button>
              </div>
            </div>
          </section>

          {activeConversation?.mode !== "regulatory" && (
            <DetailsPanel
              meta={currentMeta}
              collapsed={detailsCollapsed}
              onToggle={() => setDetailsCollapsed((v) => !v)}
            />
          )}
        </div>
      </main>
    </div>
  );
}
