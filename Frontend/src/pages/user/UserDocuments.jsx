import React, { useMemo, useRef, useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { apiForm, apiJson } from "../../auth/api.js";
import useAsyncList from "./useAsyncList.js";
import "../admin/admin.css";
import {
  PageHeader,
  Button,
  StatusPill,
  Spinner,
  EmptyState,
  SectionHeading,
  KPICard,
  Grid,
} from "../../components/ui/index.jsx";
import {
  IconStack,
  IconCheck,
  IconAlert,
  IconX,
} from "../../components/ui/Icons.jsx";

function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function statusTone(status) {
  if (status === "ready") return "ok";
  if (status === "processing") return "warn";
  if (status === "error") return "bad";
  return "muted";
}

function statusLabel(status) {
  if (status === "ready") return "Pronto";
  if (status === "processing") return "A processar";
  if (status === "error") return "Erro";
  return status || "—";
}

export default function UserDocuments() {
  const { token } = useAuth();
  const fileInputRef = useRef(null);

  const [uploading, setUploading] = useState(false);
  const [actionId, setActionId] = useState(null);
  const [error, setError] = useState("");

  const list = useAsyncList(
    () => apiJson("/user/documents?limit=100", { token }),
    [token]
  );

  const stats = useMemo(() => {
    const s = {
      total: list.items.length,
      ready: 0,
      processing: 0,
      error: 0,
      chunks: 0,
    };

    for (const d of list.items) {
      if (d.status === "ready") s.ready++;
      if (d.status === "processing") s.processing++;
      if (d.status === "error") s.error++;
      s.chunks += Number(d.chunk_count || 0);
    }

    return s;
  }, [list.items]);

  async function handleUpload(file) {
    if (!file) return;

    setUploading(true);
    setError("");

    try {
      const formData = new FormData();
      formData.append("file", file);

      await apiForm("/user/documents/upload", {
        method: "POST",
        token,
        formData,
      });

      await list.reload();

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (exc) {
      setError(exc.message || "Erro ao carregar documento.");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(documentId) {
    const ok = window.confirm("Queres apagar este documento?");
    if (!ok) return;

    setActionId(documentId);
    setError("");

    try {
      await apiJson(`/user/documents/${documentId}`, {
        method: "DELETE",
        token,
      });

      await list.reload();
    } catch (exc) {
      setError(exc.message || "Erro ao apagar documento.");
    } finally {
      setActionId(null);
    }
  }

  async function handleReprocess(documentId) {
    setActionId(documentId);
    setError("");

    try {
      await apiJson(`/user/documents/${documentId}/reprocess`, {
        method: "POST",
        token,
      });

      await list.reload();
    } catch (exc) {
      setError(exc.message || "Erro ao reprocessar documento.");
    } finally {
      setActionId(null);
    }
  }

  return (
    <>
      <PageHeader
        crumb="Cliente · Documentos"
        title={
          <>
            Documentos da <em>empresa</em>
          </>
        }
        sub="Carrega PDFs, DOCX ou TXT para o chatbot usar como contexto complementar às fontes normativas."
        actions={
          <Button variant="ghost" size="small" onClick={list.reload}>
            Recarregar
          </Button>
        }
      />

      <Grid cols={4} style={{ marginBottom: 24 }}>
        <KPICard
          label="Documentos"
          value={list.loading ? "…" : stats.total}
          icon={<IconStack size={16} />}
        />

        <KPICard
          label="Prontos"
          value={list.loading ? "…" : stats.ready}
          deltaDir="up"
          delta="usáveis pelo chatbot"
          icon={<IconCheck size={16} />}
        />

        <KPICard
          label="A processar"
          value={list.loading ? "…" : stats.processing}
          icon={<IconAlert size={16} />}
        />

        <KPICard
          label="Chunks indexados"
          value={list.loading ? "…" : stats.chunks}
          icon={<IconStack size={16} />}
        />
      </Grid>

      <div
        style={{
          background: "var(--paper)",
          border: "1px solid var(--cream-edge)",
          borderRadius: "var(--r-lg)",
          padding: 18,
          marginBottom: 20,
        }}
      >
        <SectionHeading>Adicionar documento</SectionHeading>

        <p
          style={{
            marginTop: 0,
            color: "var(--ink-muted)",
            fontSize: 14,
            lineHeight: 1.55,
          }}
        >
          Estes documentos são privados da tua conta. O chatbot pode usá-los como
          contexto interno, mas o MDR e o AI Act continuam a prevalecer quando
          houver conflito.
        </p>

        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
            onChange={(ev) => handleUpload(ev.target.files?.[0])}
            disabled={uploading}
          />

          {uploading && (
            <StatusPill tone="warn">A carregar e indexar...</StatusPill>
          )}
        </div>

        <div
          style={{
            marginTop: 10,
            fontSize: 12,
            color: "var(--ink-faded)",
          }}
        >
          Formatos aceites: PDF, DOCX e TXT.
        </div>
      </div>

      {(error || list.error) && (
        <div
          style={{
            padding: "12px 14px",
            background: "rgba(162,45,45,0.06)",
            borderLeft: "3px solid var(--missing)",
            borderRadius: 4,
            color: "var(--missing)",
            fontSize: 13,
            marginBottom: 18,
          }}
        >
          {error || list.error}
        </div>
      )}

      {list.loading && <Spinner label="A carregar documentos" />}

      {!list.loading && !list.error && list.items.length === 0 && (
        <EmptyState
          title="Ainda não há documentos"
          message="Carrega um PDF, DOCX ou TXT para o chatbot poder usar documentos internos como contexto complementar."
        />
      )}

      {list.items.length > 0 && (
        <>
          <SectionHeading>{list.items.length} documento(s)</SectionHeading>

          {list.items.map((doc) => (
            <article key={doc.id} className="admin-row">
              <div>
                <div className="admin-row__primary">
                  {doc.original_filename}
                </div>

                <div className="admin-row__meta">
                  {formatBytes(doc.size_bytes)} · {doc.chunk_count || 0} chunks ·{" "}
                  {(doc.created_at || "").slice(0, 16).replace("T", " ")}
                </div>

                {doc.error_message && (
                  <div
                    style={{
                      marginTop: 8,
                      color: "var(--missing)",
                      fontSize: 12,
                      lineHeight: 1.45,
                    }}
                  >
                    {doc.error_message}
                  </div>
                )}
              </div>

              <div className="admin-row__pills">
                <StatusPill tone={statusTone(doc.status)}>
                  {statusLabel(doc.status)}
                </StatusPill>

                {doc.status === "ready" && (
                  <StatusPill tone="ok">Usável no chatbot</StatusPill>
                )}
              </div>

              <div
                style={{
                  display: "flex",
                  gap: 8,
                  justifyContent: "flex-end",
                  gridColumn: "1 / -1",
                  marginTop: 10,
                }}
              >
                {doc.status === "error" && (
                  <Button
                    size="small"
                    variant="ghost"
                    onClick={() => handleReprocess(doc.id)}
                    disabled={actionId === doc.id}
                  >
                    Reprocessar
                  </Button>
                )}

                <Button
                  size="small"
                  variant="danger"
                  onClick={() => handleDelete(doc.id)}
                  disabled={actionId === doc.id}
                >
                  <IconX size={12} /> Apagar
                </Button>
              </div>
            </article>
          ))}
        </>
      )}
    </>
  );
}