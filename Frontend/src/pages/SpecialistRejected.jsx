import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiForm, apiJson } from "../auth/api.js";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";

const ALLOWED = [".pdf", ".jpg", ".jpeg", ".png"];

export default function SpecialistRejected() {
  const { token, user, logout } = useAuth();
  const navigate = useNavigate();
  const [reason, setReason] = useState("");
  const [files, setFiles] = useState([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    async function fetchProfile() {
      try {
        const me = await apiJson("/auth/me", { token });
        setReason(me.specialist_profile?.rejection_reason || "");
        if (me.status === "active") navigate("/app", { replace: true });
        if (me.status === "pending") navigate("/specialist/pending", { replace: true });
      } catch (err) {
        setError(err.message || "Erro ao carregar perfil.");
      }
    }
    fetchProfile();
  }, [token, navigate]);

  function handleFiles(e) {
    const next = Array.from(e.target.files || []);
    for (const f of next) {
      const lower = f.name.toLowerCase();
      if (!ALLOWED.some((ext) => lower.endsWith(ext))) {
        setError(`Formato não permitido: ${f.name}.`);
        e.target.value = "";
        return;
      }
    }
    setError("");
    setFiles(next);
  }

  async function handleResubmit(e) {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (files.length === 0) {
      setError("Submeta pelo menos um documento.");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      for (const f of files) fd.append("credentials", f);
      await apiForm("/specialist/resubmit", { formData: fd, token });
      setSuccess("Documentos submetidos. O seu registo voltou a ficar pendente.");
      setFiles([]);
      setTimeout(() => navigate("/specialist/pending", { replace: true }), 1500);
    } catch (err) {
      setError(err.message || "Erro ao resubmeter.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Registo rejeitado"
      subtitle="O administrador pediu documentação adicional. Reveja o motivo e submeta novos documentos."
      footer={
        <button onClick={() => { logout(); navigate("/login", { replace: true }); }} style={{ ...field.ghostBtn, marginTop: 0 }}>
          Terminar sessão
        </button>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink-muted)", letterSpacing: 0.4, textTransform: "uppercase", marginBottom: 6 }}>
          Olá {user?.full_name}
        </div>
        <div style={{ ...field.error, marginTop: 0 }}>
          <strong>Motivo da rejeição:</strong>
          <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{reason || "Sem motivo indicado."}</div>
        </div>
      </div>
      <form onSubmit={handleResubmit}>
        <div style={field.group}>
          <label style={field.label}>Novos documentos</label>
          <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={handleFiles} style={{ ...field.input, padding: 8 }} />
          {files.length > 0 && (
            <div style={field.helper}>
              {files.length} ficheiro(s): {files.map((f) => f.name).join(", ")}
            </div>
          )}
        </div>
        {error && <div style={field.error}>{error}</div>}
        {success && <div style={field.success}>{success}</div>}
        <button type="submit" disabled={loading} style={{ ...field.primaryBtn, opacity: loading ? 0.7 : 1 }}>
          {loading ? "A submeter..." : "Submeter novos documentos"}
        </button>
      </form>
    </AuthLayout>
  );
}
