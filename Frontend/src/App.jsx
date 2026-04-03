import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ShieldCheck,
  Plus,
  MessageSquare,
  Send,
  Server,
  AlertCircle,
  Database,
  FileText,
  CheckCircle2,
  Trash2,
} from "lucide-react";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_QUESTION = "";
const STORAGE_KEY = "bridgemedai_chat_state_v1";

function createConversation(title = "Nova conversa") {
  return {
    id: crypto.randomUUID(),
    title,
    messages: [],
    meta: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

function formatConversationTitle(text) {
  if (!text) return "Nova conversa";
  return text.length > 42 ? `${text.slice(0, 42)}...` : text;
}

function SourceCard({ source, index }) {
  return (
    <div style={styles.sourceCard}>
      <div style={styles.sourceBadgeRow}>
        <span style={styles.badge}>Fonte {index + 1}</span>
        {source.short_name && <span style={styles.badgeOutline}>{source.short_name}</span>}
        {source.section_type && <span style={styles.badgeOutline}>{source.section_type}</span>}
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={styles.sourceTitle}>{source.citation_label || "Sem citação"}</div>
        <div style={styles.sourceSubtitle}>
          {source.section_number || ""}
          {source.section_title ? ` — ${source.section_title}` : ""}
        </div>
      </div>

      <div style={styles.sourceMeta}>
        <div>
          <strong>Páginas:</strong> {source.page_start ?? "-"} - {source.page_end ?? "-"}
        </div>
        {typeof source.score_adjusted === "number" && (
          <div>
            <strong>Score:</strong> {source.score_adjusted.toFixed(4)}
          </div>
        )}
      </div>
    </div>
  );
}

function MessageBubble({ role, content }) {
  const isUser = role === "user";

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
      }}
    >
      <div
        style={{
          ...styles.messageBubble,
          ...(isUser ? styles.userBubble : styles.assistantBubble),
        }}
      >
        <div style={styles.messageRole}>{isUser ? "Tu" : "BridgeMedAI"}</div>
        <div style={styles.messageText}>{content}</div>
      </div>
    </div>
  );
}

export default function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [input, setInput] = useState(DEFAULT_QUESTION);

  const [health, setHealth] = useState({
    loading: false,
    data: null,
    error: "",
  });

  const [chatState, setChatState] = useState({
    loading: false,
    error: "",
  });

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

  const normalizedBaseUrl = useMemo(
    () => apiBaseUrl.trim().replace(/\/$/, ""),
    [apiBaseUrl]
  );

  const activeConversation =
    conversations.find((conv) => conv.id === activeConversationId) || conversations[0];

  useEffect(() => {
    if (!activeConversationId && conversations.length > 0) {
      setActiveConversationId(conversations[0].id);
    }
  }, [activeConversationId, conversations]);

  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          conversations,
          activeConversationId,
        })
      );
    } catch {
      // ignorar erros de storage
    }
  }, [conversations, activeConversationId]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [activeConversation?.messages, chatState.loading]);

  async function callApi(path, options = {}) {
    const response = await fetch(`${normalizedBaseUrl}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
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
    setHealth({ loading: true, data: null, error: "" });

    try {
      const data = await callApi("/health", { method: "GET" });
      setHealth({ loading: false, data, error: "" });
    } catch (error) {
      setHealth({
        loading: false,
        data: null,
        error: error.message || "Erro ao ligar ao backend.",
      });
    }
  }

  function handleNewConversation() {
    const newConversation = createConversation("Nova conversa");
    setConversations((prev) => [newConversation, ...prev]);
    setActiveConversationId(newConversation.id);
    setInput("");
    setChatState({ loading: false, error: "" });
  }

  function handleDeleteConversation(event, conversationId) {
    event.stopPropagation();

    const confirmed = window.confirm("Queres mesmo apagar esta conversa?");
    if (!confirmed) return;

    setConversations((prev) => {
      const filtered = prev.filter((conv) => conv.id !== conversationId);

      if (filtered.length === 0) {
        const fallbackConversation = createConversation("Nova conversa");
        setActiveConversationId(fallbackConversation.id);
        return [fallbackConversation];
      }

      if (conversationId === activeConversationId) {
        setActiveConversationId(filtered[0].id);
      }

      return filtered;
    });
  }

  async function sendMessage() {
    const question = input.trim();
    if (!question || !activeConversation || chatState.loading) return;

    setChatState({ loading: true, error: "" });

    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
    };

    setConversations((prev) =>
      prev.map((conv) =>
        conv.id === activeConversation.id
          ? {
              ...conv,
              title:
                conv.messages.length === 0
                  ? formatConversationTitle(question)
                  : conv.title,
              messages: [...conv.messages, userMessage],
              updatedAt: new Date().toISOString(),
            }
          : conv
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
      };

      setConversations((prev) =>
        prev.map((conv) =>
          conv.id === activeConversation.id
            ? {
                ...conv,
                messages: [...conv.messages, assistantMessage],
                meta: {
                  intent: data.intent || null,
                  target_docs: data.target_docs || [],
                  retrieved_sources: data.retrieved_sources || [],
                  generation_sources: data.generation_sources || [],
                  raw: data,
                },
                updatedAt: new Date().toISOString(),
              }
            : conv
        )
      );

      setChatState({ loading: false, error: "" });
    } catch (error) {
      setChatState({
        loading: false,
        error: error.message || "Erro no endpoint /chat.",
      });
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  const currentMeta = activeConversation?.meta || null;
  const retrievedSources = currentMeta?.retrieved_sources || [];
  const generationSources = currentMeta?.generation_sources || [];

  return (
    <div style={styles.page}>
      <div style={styles.appShell}>
        <aside style={styles.sidebar}>
          <div style={styles.sidebarHeader}>
            <div style={styles.logoBox}>
              <ShieldCheck size={20} />
            </div>
            <div>
              <div style={styles.sidebarTitle}>BridgeMedAI</div>
              <div style={styles.sidebarSubtitle}>Compliance Assistant</div>
            </div>
          </div>

          <button style={styles.newChatButton} onClick={handleNewConversation}>
            <Plus size={16} />
            Nova conversa
          </button>

          <div style={styles.sidebarSectionTitle}>Histórico</div>

          <div style={styles.historyList}>
            {conversations.map((conversation) => {
              const isActive = conversation.id === activeConversation?.id;

              return (
                <div
                  key={conversation.id}
                  onClick={() => setActiveConversationId(conversation.id)}
                  style={{
                    ...styles.historyItem,
                    ...(isActive ? styles.historyItemActive : {}),
                  }}
                >
                  <div style={styles.historyItemLeft}>
                    <MessageSquare size={15} />
                    <span style={styles.historyItemText}>{conversation.title}</span>
                  </div>

                  <button
                    onClick={(event) => handleDeleteConversation(event, conversation.id)}
                    style={styles.deleteButton}
                    title="Apagar conversa"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              );
            })}
          </div>
        </aside>

        <main style={styles.mainArea}>
          <header style={styles.topbar}>
            <div>
              <h1 style={styles.mainTitle}>BridgeMedAI</h1>
              <p style={styles.mainSubtitle}>
                Framework Integrado de Conformidade para Dispositivos Médicos com
                Inteligência Artificial
              </p>
            </div>

            <div style={styles.topbarRight}>
              <div style={styles.apiConfig}>
                <label style={styles.apiLabel}>Base URL da API</label>
                <input
                  style={styles.apiInput}
                  value={apiBaseUrl}
                  onChange={(e) => setApiBaseUrl(e.target.value)}
                  placeholder="http://127.0.0.1:8000"
                />
              </div>

              <button style={styles.healthButton} onClick={checkHealth}>
                <Server size={16} />
                Testar ligação
              </button>
            </div>
          </header>

          {health.error && (
            <div style={{ ...styles.statusBox, ...styles.errorBox }}>
              <AlertCircle size={16} />
              <span>{health.error}</span>
            </div>
          )}

          {health.data && (
            <div style={{ ...styles.statusBox, ...styles.successBox }}>
              <CheckCircle2 size={16} />
              <span>Backend ligado com sucesso: {JSON.stringify(health.data)}</span>
            </div>
          )}

          <div style={styles.chatLayout}>
            <section style={styles.chatColumn}>
              <div style={styles.chatWindow}>
                {activeConversation?.messages?.length ? (
                  <div style={styles.messagesList}>
                    {activeConversation.messages.map((message) => (
                      <MessageBubble
                        key={message.id}
                        role={message.role}
                        content={message.content}
                      />
                    ))}

                    {chatState.loading && (
                      <div style={{ display: "flex", justifyContent: "flex-start" }}>
                        <div style={{ ...styles.messageBubble, ...styles.assistantBubble }}>
                          <div style={styles.messageRole}>BridgeMedAI</div>
                          <div style={styles.messageText}>A gerar resposta...</div>
                        </div>
                      </div>
                    )}

                    <div ref={messagesEndRef} />
                  </div>
                ) : (
                  <div style={styles.emptyChat}>
                    <div style={styles.emptyChatIcon}>
                      <MessageSquare size={26} />
                    </div>
                    <h2 style={{ margin: "14px 0 8px 0" }}>Bem-vindo ao BridgeMedAI</h2>
                    <p style={styles.emptyChatText}>
                      Faz uma pergunta sobre MDR, AI Act, classificação, requisitos ou
                      conformidade do teu dispositivo médico.
                    </p>
                  </div>
                )}
              </div>

              {chatState.error && (
                <div style={{ ...styles.statusBox, ...styles.errorBox, marginTop: 12 }}>
                  <AlertCircle size={16} />
                  <span>{chatState.error}</span>
                </div>
              )}

              <div style={styles.inputArea}>
                <textarea
                  style={styles.chatInput}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={4}
                  placeholder="Escreve a tua pergunta..."
                />
                <div style={styles.inputActions}>
                  <div style={styles.inputHint}>Enter para enviar · Shift+Enter para nova linha</div>
                  <button
                    style={{
                      ...styles.sendButton,
                      ...(chatState.loading || !input.trim() ? styles.sendButtonDisabled : {}),
                    }}
                    onClick={sendMessage}
                    disabled={chatState.loading || !input.trim()}
                  >
                    <Send size={16} />
                    Enviar
                  </button>
                </div>
              </div>
            </section>

            <aside style={styles.sourcesPanel}>
              <div style={styles.sourcesPanelHeader}>
                <h3 style={{ margin: 0 }}>Detalhes da resposta</h3>
              </div>

              <div style={styles.metaSection}>
                <div style={styles.metaLabel}>Intent</div>
                <div style={styles.badgeRow}>
                  {currentMeta?.intent ? (
                    <span style={styles.badge}>{currentMeta.intent}</span>
                  ) : (
                    <span style={styles.emptyMeta}>Sem intent ainda</span>
                  )}
                </div>
              </div>

              <div style={styles.metaSection}>
                <div style={styles.metaLabel}>Documentos-alvo</div>
                <div style={styles.badgeRow}>
                  {currentMeta?.target_docs?.length ? (
                    currentMeta.target_docs.map((doc) => (
                      <span key={doc} style={styles.badgeOutline}>
                        {doc}
                      </span>
                    ))
                  ) : (
                    <span style={styles.emptyMeta}>Sem documentos ainda</span>
                  )}
                </div>
              </div>

              <div style={styles.sourcesBlock}>
                <div style={styles.sourcesBlockTitle}>
                  <Database size={16} />
                  <span>Fontes recuperadas</span>
                </div>

                <div style={styles.sourcesList}>
                  {retrievedSources.length ? (
                    retrievedSources.map((source, index) => (
                      <SourceCard
                        key={`retrieved-${index}`}
                        source={source}
                        index={index}
                      />
                    ))
                  ) : (
                    <div style={styles.emptyPanelText}>Ainda não há fontes recuperadas.</div>
                  )}
                </div>
              </div>

              <div style={styles.sourcesBlock}>
                <div style={styles.sourcesBlockTitle}>
                  <FileText size={16} />
                  <span>Fontes usadas na geração</span>
                </div>

                <div style={styles.sourcesList}>
                  {generationSources.length ? (
                    generationSources.map((source, index) => (
                      <SourceCard
                        key={`generation-${index}`}
                        source={source}
                        index={index}
                      />
                    ))
                  ) : (
                    <div style={styles.emptyPanelText}>
                      Ainda não há fontes usadas na geração.
                    </div>
                  )}
                </div>
              </div>
            </aside>
          </div>
        </main>
      </div>
    </div>
  );
}

const styles = {
  page: {
  height: "100dvh",
  background: "#f3f4f6",
  color: "#0f172a",
  fontFamily:
    'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  overflow: "hidden",
  },

  appShell: {
  display: "grid",
  gridTemplateColumns: "280px 1fr",
  height: "100%",
  minHeight: 0,
  },

  sidebar: {
  background: "#0f172a",
  color: "#fff",
  padding: "20px 16px",
  display: "flex",
  flexDirection: "column",
  gap: 18,
  height: "100%",
  minHeight: 0,
  boxSizing: "border-box",
  },

  sidebarHeader: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    marginBottom: 4,
  },

  logoBox: {
    width: 42,
    height: 42,
    borderRadius: 12,
    background: "#1e293b",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },

  sidebarTitle: {
    fontSize: 18,
    fontWeight: 700,
  },

  sidebarSubtitle: {
    fontSize: 12,
    color: "#94a3b8",
  },

  newChatButton: {
    background: "#fff",
    color: "#0f172a",
    border: "none",
    borderRadius: 12,
    padding: "12px 14px",
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontWeight: 600,
    cursor: "pointer",
  },

  sidebarSectionTitle: {
    fontSize: 13,
    fontWeight: 700,
    color: "#cbd5e1",
    marginTop: 8,
  },

  historyList: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    overflowY: "auto",
    minHeight: 0,
  },

  historyItem: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    padding: "12px",
    borderRadius: 12,
    border: "1px solid transparent",
    background: "transparent",
    color: "#e2e8f0",
    textAlign: "left",
    cursor: "pointer",
  },

  historyItemActive: {
    background: "#1e293b",
    border: "1px solid #334155",
  },

  historyItemLeft: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    minWidth: 0,
    flex: 1,
  },

  historyItemText: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontSize: 14,
  },

  deleteButton: {
    width: 28,
    height: 28,
    minWidth: 28,
    borderRadius: 8,
    border: "none",
    background: "transparent",
    color: "#94a3b8",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    cursor: "pointer",
    flexShrink: 0,
  },

  mainArea: {
  padding: "22px 28px 22px",
  display: "flex",
  flexDirection: "column",
  gap: 14,
  height: "100%",
  minHeight: 0,
  boxSizing: "border-box",
  overflow: "hidden",
  },

  topbar: {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 16,
  flexWrap: "wrap",
  flexShrink: 0,
  },

  mainTitle: {
  margin: 0,
  fontSize: 30,
  lineHeight: 1.1,
  },

  mainSubtitle: {
  margin: "4px 0 0 0",
  color: "#64748b",
  fontSize: 15,
  lineHeight: 1.4,
  maxWidth: 720,
  },

  topbarRight: {
  display: "flex",
  alignItems: "flex-end",
  gap: 10,
  flexWrap: "wrap",
  },

  apiConfig: {
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },

  apiLabel: {
    fontSize: 13,
    fontWeight: 700,
    color: "#334155",
  },

  apiInput: {
  minWidth: 240,
  padding: "10px 12px",
  borderRadius: 12,
  border: "1px solid #cbd5e1",
  background: "#fff",
  fontSize: 14,
  },

  healthButton: {
  padding: "10px 14px",
  borderRadius: 12,
  border: "none",
  background: "#0f172a",
  color: "#fff",
  display: "flex",
  alignItems: "center",
  gap: 8,
  cursor: "pointer",
  fontWeight: 600,
  },

  statusBox: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "12px 14px",
    borderRadius: 12,
    fontSize: 14,
    flexShrink: 0,
  },

  successBox: {
    background: "#ecfdf5",
    color: "#047857",
    border: "1px solid #a7f3d0",
  },

  errorBox: {
    background: "#fef2f2",
    color: "#b91c1c",
    border: "1px solid #fecaca",
  },

  chatLayout: {
  display: "grid",
  gridTemplateColumns: "1.4fr 0.9fr",
  gap: 20,
  flex: 1,
  minHeight: 0,
  alignItems: "stretch",
  },

  chatColumn: {
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
    height: "100%",
    overflow: "hidden",
  },

  chatWindow: {
  flex: 1,
  minHeight: 0,
  background: "#fff",
  borderRadius: 20,
  padding: 24,
  border: "1px solid #e5e7eb",
  overflowY: "auto",
  overflowX: "hidden",
  },

  messagesList: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },

  messageBubble: {
    maxWidth: "78%",
    borderRadius: 18,
    padding: "14px 16px",
    boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
  },

  userBubble: {
    background: "#0f172a",
    color: "#fff",
  },

  assistantBubble: {
    background: "#f8fafc",
    color: "#0f172a",
    border: "1px solid #e2e8f0",
  },

  messageRole: {
    fontSize: 12,
    fontWeight: 700,
    opacity: 0.8,
    marginBottom: 6,
  },

  messageText: {
    whiteSpace: "pre-wrap",
    lineHeight: 1.7,
    fontSize: 15,
  },

  emptyChat: {
    height: "100%",
    minHeight: 360,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    textAlign: "center",
    color: "#64748b",
    padding: 24,
  },

  emptyChatIcon: {
    width: 58,
    height: 58,
    borderRadius: 16,
    background: "#eef2ff",
    color: "#1e293b",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },

  emptyChatText: {
    maxWidth: 520,
    lineHeight: 1.7,
    margin: 0,
  },

  inputArea: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: 20,
    padding: 16,
    marginTop: 14,
    flexShrink: 0,
  },

  chatInput: {
    width: "100%",
    border: "1px solid #cbd5e1",
    borderRadius: 14,
    padding: 14,
    resize: "none",
    fontSize: 15,
    outline: "none",
    boxSizing: "border-box",
    minHeight: 96,
    maxHeight: 180,
    overflowY: "auto",
  },

  inputActions: {
    marginTop: 12,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },

  inputHint: {
    fontSize: 13,
    color: "#64748b",
  },

  sendButton: {
    padding: "11px 16px",
    borderRadius: 12,
    border: "none",
    background: "#0f172a",
    color: "#fff",
    display: "flex",
    alignItems: "center",
    gap: 8,
    cursor: "pointer",
    fontWeight: 600,
  },

  sendButtonDisabled: {
    opacity: 0.55,
    cursor: "not-allowed",
  },

  sourcesPanel: {
  background: "#fff",
  borderRadius: 20,
  border: "1px solid #e5e7eb",
  padding: 24,
  overflowY: "auto",
  minHeight: 0,
  height: "100%",
  },

  sourcesPanelHeader: {
    marginBottom: 16,
  },

  metaSection: {
    marginBottom: 18,
  },

  metaLabel: {
    fontSize: 13,
    fontWeight: 700,
    color: "#334155",
    marginBottom: 8,
  },

  badgeRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },

  badge: {
    padding: "5px 10px",
    borderRadius: 999,
    background: "#e2e8f0",
    fontSize: 12,
    color: "#0f172a",
  },

  badgeOutline: {
    padding: "5px 10px",
    borderRadius: 999,
    border: "1px solid #cbd5e1",
    background: "#fff",
    fontSize: 12,
    color: "#0f172a",
  },

  emptyMeta: {
    fontSize: 13,
    color: "#64748b",
  },

  sourcesBlock: {
    marginTop: 20,
  },

  sourcesBlockTitle: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontWeight: 700,
    marginBottom: 12,
  },

  sourcesList: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },

  emptyPanelText: {
    color: "#64748b",
    fontSize: 14,
  },

  sourceCard: {
    border: "1px solid #e2e8f0",
    borderRadius: 16,
    padding: 14,
    background: "#fff",
  },

  sourceBadgeRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 8,
  },

  sourceTitle: {
    fontSize: 15,
    fontWeight: 700,
    color: "#0f172a",
  },

  sourceSubtitle: {
    marginTop: 4,
    color: "#64748b",
    fontSize: 13,
    lineHeight: 1.5,
  },

  sourceMeta: {
    marginTop: 12,
    fontSize: 13,
    color: "#334155",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
};