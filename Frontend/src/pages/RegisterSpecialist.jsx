import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiForm } from "../auth/api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";

const ALLOWED = [".pdf", ".jpg", ".jpeg", ".png"];

export default function RegisterSpecialist() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    confirm: "",
    specialty: "",
    institution: "",
    country: "",
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
    if (files.length === 0) {
      setError("Submeta pelo menos um documento comprovativo.");
      return;
    }
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("full_name", form.full_name.trim());
      fd.append("email", form.email.trim());
      fd.append("password", form.password);
      fd.append("specialty", form.specialty.trim());
      fd.append("institution", form.institution.trim());
      fd.append("country", form.country.trim());
      for (const f of files) fd.append("credentials", f);
      const payload = await apiForm("/auth/register-specialist", { formData: fd });
      login(payload);
      navigate("/specialist/pending", { replace: true });
    } catch (err) {
      setError(err.message || "Erro ao submeter o registo.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Registar especialista"
      subtitle="O acesso fica pendente até validação por um administrador."
      footer={<Link to="/register" style={{ color: "var(--forest)", fontWeight: 600 }}>← Voltar</Link>}
    >
      <form onSubmit={handleSubmit} noValidate>
        <div style={field.group}>
          <label style={field.label}>Nome completo</label>
          <input required value={form.full_name} onChange={(e) => update("full_name", e.target.value)} style={field.input} />
        </div>
        <div style={field.group}>
          <label style={field.label}>Email</label>
          <input required type="email" autoComplete="email" value={form.email} onChange={(e) => update("email", e.target.value)} style={field.input} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={field.group}>
            <label style={field.label}>Password</label>
            <input required type="password" autoComplete="new-password" value={form.password} onChange={(e) => update("password", e.target.value)} style={field.input} />
          </div>
          <div style={field.group}>
            <label style={field.label}>Confirmar</label>
            <input required type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => update("confirm", e.target.value)} style={field.input} />
          </div>
        </div>
        <div style={field.group}>
          <label style={field.label}>Especialidade</label>
          <input required placeholder="Ex.: Cardiologia" value={form.specialty} onChange={(e) => update("specialty", e.target.value)} style={field.input} />
        </div>
        <div style={field.group}>
          <label style={field.label}>Instituição</label>
          <input required placeholder="Ex.: Hospital de São João" value={form.institution} onChange={(e) => update("institution", e.target.value)} style={field.input} />
        </div>
        <div style={field.group}>
          <label style={field.label}>País</label>
          <input required value={form.country} onChange={(e) => update("country", e.target.value)} style={field.input} />
        </div>
        <div style={field.group}>
          <label style={field.label}>Credenciais (PDF, JPG, PNG)</label>
          <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={handleFiles} style={{ ...field.input, padding: 8 }} />
          {files.length > 0 && (
            <div style={field.helper}>
              {files.length} ficheiro(s) seleccionado(s): {files.map((f) => f.name).join(", ")}
            </div>
          )}
        </div>
        {error && <div style={field.error}>{error}</div>}
        <button type="submit" disabled={loading} style={{ ...field.primaryBtn, opacity: loading ? 0.7 : 1 }}>
          {loading ? "A submeter..." : "Submeter registo"}
        </button>
      </form>
    </AuthLayout>
  );
}
