import React, { useMemo, useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiDownload, apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import {
  PageHeader, Card, Button, StatusPill, Spinner, EmptyState, SectionHeading, Grid,
} from "../../components/ui/index.jsx";
import {
  IconStack, IconScroll, IconCheckList, IconShield, IconActivity,
} from "../../components/ui/Icons.jsx";

const DOC_TYPE_LABEL = {
  TMP: "Template",
  FRM: "Formulário",
  SOP: "Procedimento",
  LST: "Lista",
};

const DOC_TYPE_ICON = {
  TMP: <IconScroll size={14} />,
  FRM: <IconCheckList size={14} />,
  SOP: <IconShield size={14} />,
  LST: <IconActivity size={14} />,
};

export default function UserTemplates() {
  const { token } = useAuth();
  const [category, setCategory] = useState("");
  const [regulation, setRegulation] = useState("");
  const [theme, setTheme] = useState("");
  const [docType, setDocType] = useState("");
  const [search, setSearch] = useState("");
  const [downloadingId, setDownloadingId] = useState(null);

  const templates = useAsyncList(() => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (regulation) params.set("regulation", regulation);
    if (theme) params.set("theme", theme);
    if (docType) params.set("doc_type", docType);
    const qs = params.toString();
    return apiJson(`/templates${qs ? `?${qs}` : ""}`, { token });
  }, [token, category, regulation, theme, docType]);

  const categories = useAsyncList(
    () => apiJson("/templates/categories", { token }),
    [token]
  );

  const tags = useAsyncList(
    () => apiJson("/templates/tags", { token }).then((d) => [d]),
    [token]
  );

  const filtered = useMemo(() => {
    if (!search.trim()) return templates.items;
    const q = search.trim().toLowerCase();
    return templates.items.filter((t) =>
      (t.name || "").toLowerCase().includes(q) ||
      (t.id || "").toLowerCase().includes(q) ||
      (t.description || "").toLowerCase().includes(q) ||
      (t.keywords || []).some((k) => k.toLowerCase().includes(q))
    );
  }, [templates.items, search]);

  const tagsData = tags.items[0] || {};
  const regulations = tagsData.regulations_in_use || [];
  const themes = tagsData.themes_in_use || [];

  async function handleDownload(template) {
    setDownloadingId(template.id);
    try {
      await apiDownload(`/templates/${encodeURIComponent(template.id)}/download`, {
        token,
        filename: template.file?.split("/").pop() || `${template.id}.docx`,
      });
    } catch (err) {
      // erro silencioso por agora — apiDownload mostra o ficheiro
    } finally {
      setDownloadingId(null);
    }
  }

  const grouped = useMemo(() => {
    const map = {};
    for (const t of filtered) {
      if (!map[t.category]) map[t.category] = [];
      map[t.category].push(t);
    }
    return map;
  }, [filtered]);

  return (
    <>
      <PageHeader
        crumb="Cliente · Recursos"
        title={<>Catálogo de <em>templates</em></>}
        sub="Templates regulatórios prontos a usar (Fraunhofer). Filtra por categoria, regulamento ou tema e descarrega o ficheiro original."
        actions={
          <Button variant="ghost" size="small" onClick={templates.reload}>
            Recarregar
          </Button>
        }
      />

      <div className="admin-filterbar">
        <span className="admin-filterbar__label">Filtrar</span>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Todas as categorias</option>
          {(categories.items || []).map((c) => (
            <option key={c.category} value={c.category}>{c.category} ({c.count})</option>
          ))}
        </select>
        <select value={regulation} onChange={(e) => setRegulation(e.target.value)}>
          <option value="">Qualquer regulamento</option>
          {regulations.map((r) => (
            <option key={r.tag} value={r.tag}>{r.tag} ({r.count})</option>
          ))}
        </select>
        <select value={theme} onChange={(e) => setTheme(e.target.value)}>
          <option value="">Qualquer tema</option>
          {themes.map((t) => (
            <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>
          ))}
        </select>
        <select value={docType} onChange={(e) => setDocType(e.target.value)}>
          <option value="">Todos os tipos</option>
          <option value="TMP">Templates</option>
          <option value="FRM">Formulários</option>
          <option value="SOP">Procedimentos</option>
          <option value="LST">Listas</option>
        </select>
        <input
          type="text"
          placeholder="Procurar por nome, ID, descrição…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ flex: 1, minWidth: 220 }}
        />
      </div>

      {templates.loading && <Spinner label="A carregar templates" />}
      {templates.error && (
        <div style={{ padding: "12px 14px", background: "rgba(162,45,45,0.06)", borderLeft: "3px solid var(--missing)", borderRadius: 4, color: "var(--missing)", fontSize: 13 }}>
          {templates.error}
        </div>
      )}

      {!templates.loading && !templates.error && filtered.length === 0 && (
        <EmptyState
          title="Sem templates"
          message={search ? `Nenhum match para "${search}".` : "Nada para mostrar com os filtros atuais."}
        />
      )}

      {filtered.length > 0 && (
        <>
          <SectionHeading>{filtered.length} template(s)</SectionHeading>
          {Object.entries(grouped).map(([cat, list]) => (
            <div key={cat} style={{ marginBottom: 28 }}>
              <h2 style={{
                fontFamily: "var(--display)",
                fontSize: 20,
                fontWeight: 500,
                color: "var(--forest-deep)",
                margin: "0 0 12px",
                letterSpacing: "-0.01em",
              }}>
                {cat}
                <span style={{
                  fontFamily: "var(--mono)",
                  fontSize: 11,
                  color: "var(--ink-faded)",
                  marginLeft: 8,
                  letterSpacing: 0.04,
                }}>
                  · {list.length}
                </span>
              </h2>
              <Grid cols={2}>
                {list.map((t) => (
                  <TemplateCard
                    key={t.id}
                    template={t}
                    busy={downloadingId === t.id}
                    onDownload={() => handleDownload(t)}
                  />
                ))}
              </Grid>
            </div>
          ))}
        </>
      )}
    </>
  );
}

function TemplateCard({ template, busy, onDownload }) {
  const docLabel = DOC_TYPE_LABEL[template.doc_type] || template.doc_type;
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          fontFamily: "var(--mono)",
          fontSize: 10,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "var(--forest)",
        }}>
          {DOC_TYPE_ICON[template.doc_type]}
          {docLabel}
        </div>
        <code style={{
          fontFamily: "var(--mono)",
          fontSize: 10,
          color: "var(--ink-faded)",
          letterSpacing: 0.04,
        }}>
          {template.id}
        </code>
      </div>

      <h3 style={{
        margin: "4px 0 8px",
        fontFamily: "var(--display)",
        fontSize: 17,
        fontWeight: 500,
        color: "var(--forest-deep)",
        lineHeight: 1.25,
      }}>
        {template.name}
      </h3>

      {template.description && (
        <p style={{
          margin: "0 0 12px",
          fontSize: 13,
          color: "var(--ink-muted)",
          lineHeight: 1.5,
        }}>
          {template.description.length > 180
            ? template.description.slice(0, 180) + "…"
            : template.description}
        </p>
      )}

      {template.regulations?.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 12 }}>
          {template.regulations.slice(0, 4).map((r) => (
            <StatusPill key={r} tone="muted">{r}</StatusPill>
          ))}
          {template.regulations.length > 4 && (
            <span style={{ fontFamily: "var(--mono)", fontSize: 10, color: "var(--ink-faded)", alignSelf: "center" }}>
              +{template.regulations.length - 4}
            </span>
          )}
        </div>
      )}

      <Button onClick={onDownload} disabled={busy} size="small">
        {busy ? "A descarregar…" : "Descarregar"}
      </Button>
    </Card>
  );
}
