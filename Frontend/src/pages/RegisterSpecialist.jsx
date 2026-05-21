import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiForm } from "../auth/api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";

const ALLOWED = [".pdf", ".jpg", ".jpeg", ".png"];

/**
 * RegisterSpecialist — registo para engenheiros / consultores especializados
 * em regulamentação de dispositivos médicos (MDR, AI Act, ISO 14971, IEC 62304…).
 *
 * Narrativa atualizada: já NÃO é médico. Não pedimos especialidade clínica
 * nem hospital. Apenas nome, email, password, descrição curta opcional e
 * documentos comprovativos (CV, certificações).
 */
export default function RegisterSpecialist() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    confirm: "",
    expertise: "",   // texto livre, opcional
    organization: "", // empresa/organização, opcional
  });
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function update(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleFiles(e) {
    const next = Array.from(e.target.files || []);
    for (const f of next) {
      const lower = f.name.toLowerCase();
      if (!ALLOWED.some((ext) => lower.endsWith(ext))) {
        setError(`Formato não permitido: ${f.name}. Use PDF, JPG ou PNG.`);
        e.target.value = "";
        return;
      }
    }
    setError("");
    setFiles(next);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm) {
      setError("As passwords não coincidem.");
      return;
    }
    if (form.password.length < 8) {
      setError("A password tem de ter pelo menos 8 caracteres.");
      return;
    }
    if (files.length === 0) {
      setError("Submete pelo menos um documento comprovativo (CV, certificado, etc.).");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("full_name", form.full_name.trim());
      fd.append("email", form.email.trim());
      fd.append("password", form.password);
      // O backend aceita estes campos como Form opcionais. Reaproveitamos os
      // existentes (specialty/institution) para guardar áreas de expertise +
      // organização, sem alterar o schema da DB.
      if (form.expertise.trim()) fd.append("specialty", form.expertise.trim());
      if (form.organization.trim()) fd.append("institution", form.organization.trim());
      for (const f of files) fd.append("credentials", f);
      await apiForm("/auth/register-specialist", { formData: fd });
      // A resposta tem só { user, message } — não tem token. Vamos para o
      // login com banner informativo. Só será possível entrar quando o admin
      // aprovar a candidatura.
      navigate("/login?registered=specialist", { replace: true });
    } catch (err) {
      setError(err.message || "Erro ao submeter o registo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Registar especialista regulatório"
      subtitle="Para engenheiros / consultores especializados em MDR, AI Act, ISO 14971, IEC 62304 e normas associadas. A conta fica pendente até um administrador rever as tuas credenciais."
      footer={<Link to="/register" style={{ color: "var(--forest)", fontWeight: 600 }}>← Voltar</Link>}
    >
      <form onSubmit={handleSubmit} noValidate>
        <div style={field.group}>
          <label style={field.label}>Nome completo</label>
          <input
            required
            value={form.full_name}
            onChange={(e) => update("full_name", e.target.value)}
            style={field.input}
          />
        </div>

        <div style={field.group}>
          <label style={field.label}>Email</label>
          <input
            required
            type="email"
            autoComplete="email"
            value={form.email}
            onChange={(e) => update("email", e.target.value)}
            style={field.input}
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={field.group}>
            <label style={field.label}>Password</label>
            <input
              required
              type="password"
              autoComplete="new-password"
              value={form.password}
              onChange={(e) => update("password", e.target.value)}
              style={field.input}
              minLength={8}
            />
          </div>
          <div style={field.group}>
            <label style={field.label}>Confirmar</label>
            <input
              required
              type="password"
              autoComplete="new-password"
              value={form.confirm}
              onChange={(e) => update("confirm", e.target.value)}
              style={field.input}
              minLength={8}
            />
          </div>
        </div>

        <div style={field.group}>
          <label style={field.label}>Áreas de expertise <span style={optionalTag}>opcional</span></label>
          <input
            placeholder="Ex.: MDR + AI Act + IEC 62304"
            value={form.expertise}
            onChange={(e) => update("expertise", e.target.value)}
            style={field.input}
          />
          <div style={field.helper}>
            Ajuda o admin a perceber em que regulamentos te queres focar (texto livre).
          </div>
        </div>

        <div style={field.group}>
          <label style={field.label}>Empresa ou organização <span style={optionalTag}>opcional</span></label>
          <input
            placeholder="Ex.: BridgeMed Consulting · independente · ..."
            value={form.organization}
            onChange={(e) => update("organization", e.target.value)}
            style={field.input}
          />
        </div>

        <div style={field.group}>
          <label style={field.label}>Documentos comprovativos (PDF, JPG, PNG)</label>
          <input
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png"
            onChange={handleFiles}
            style={{ ...field.input, padding: 8 }}
          />
          <div style={field.helper}>
            CV, certificações, transcripts de cursos relevantes (ISO 13485 Lead Auditor,
            cursos de MDR, etc.). Mínimo 1 ficheiro.
          </div>
          {files.length > 0 && (
            <div style={{ ...field.helper, color: "var(--forest)", marginTop: 6 }}>
              {files.length} ficheiro(s) seleccionado(s): {files.map((f) => f.name).join(", ")}
            </div>
          )}
        </div>

        {error && <div style={field.error}>{error}</div>}

        <button
          type="submit"
          disabled={loading}
          style={{ ...field.primaryBtn, opacity: loading ? 0.7 : 1 }}
        >
          {loading ? "A submeter…" : "Submeter candidatura"}
        </button>
      </form>
    </AuthLayout>
  );
}

const optionalTag = {
  fontFamily: "var(--mono)",
  fontSize: 9,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--ink-faded)",
  marginLeft: 6,
  fontWeight: 400,
};
