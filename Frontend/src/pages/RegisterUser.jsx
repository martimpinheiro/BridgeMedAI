import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiJson } from "../auth/api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";

export default function RegisterUser() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", confirm: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function update(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm) {
      setError("As passwords não coincidem.");
      return;
    }
    setLoading(true);
    try {
      const payload = await apiJson("/auth/register-user", {
        method: "POST",
        body: { full_name: form.full_name.trim(), email: form.email.trim(), password: form.password },
      });
      login(payload);
      navigate("/app", { replace: true });
    } catch (err) {
      setError(err.message || "Erro ao criar conta.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Registar utilizador"
      subtitle="Crie a sua conta. O acesso é imediato após o registo."
      footer={
        <>
          <Link to="/register" style={{ color: "var(--forest)", fontWeight: 600 }}>← Voltar</Link>
        </>
      }
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
        <div style={field.group}>
          <label style={field.label}>Password</label>
          <input required type="password" autoComplete="new-password" value={form.password} onChange={(e) => update("password", e.target.value)} style={field.input} />
          <div style={field.helper}>Mínimo 8 caracteres, com pelo menos uma letra e um número.</div>
        </div>
        <div style={field.group}>
          <label style={field.label}>Confirmar password</label>
          <input required type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => update("confirm", e.target.value)} style={field.input} />
        </div>
        {error && <div style={field.error}>{error}</div>}
        <button type="submit" disabled={loading} style={{ ...field.primaryBtn, opacity: loading ? 0.7 : 1 }}>
          {loading ? "A criar conta..." : "Criar conta"}
        </button>
      </form>
    </AuthLayout>
  );
}
