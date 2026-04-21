import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { apiJson } from "../auth/api.js";
import { useAuth } from "../auth/AuthContext.jsx";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";

export default function InviteRegister() {
  const { token: inviteToken } = useParams();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [inviteState, setInviteState] = useState({ state: "checking", data: null, error: "" });
  const [form, setForm] = useState({ full_name: "", email: "", password: "", confirm: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    async function check() {
      try {
        const data = await apiJson(`/auth/invite/${inviteToken}`);
        if (!alive) return;
        setInviteState({ state: "valid", data, error: "" });
      } catch (err) {
        if (!alive) return;
        setInviteState({ state: "invalid", data: null, error: err.message || "Convite inválido." });
      }
    }
    check();
    return () => { alive = false; };
  }, [inviteToken]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm) {
      setError("As passwords não coincidem.");
      return;
    }
    setLoading(true);
    try {
      const payload = await apiJson("/auth/invite-register", {
        method: "POST",
        body: {
          token: inviteToken,
          full_name: form.full_name.trim(),
          email: form.email.trim(),
          password: form.password,
        },
      });
      login(payload);
      navigate("/admin", { replace: true });
    } catch (err) {
      setError(err.message || "Erro ao criar conta.");
    } finally {
      setLoading(false);
    }
  }

  if (inviteState.state === "checking") {
    return (
      <AuthLayout title="A verificar convite..." subtitle="Aguarde enquanto validamos o seu convite.">
        <div style={{ fontSize: 14, color: "var(--ink-muted)" }}>A verificar...</div>
      </AuthLayout>
    );
  }

  if (inviteState.state === "invalid") {
    return (
      <AuthLayout title="Convite inválido" subtitle="Este convite não pode ser usado.">
        <div style={field.error}>{inviteState.error}</div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Registo de administrador"
      subtitle="Use o convite para criar a sua conta de administrador."
    >
      <form onSubmit={handleSubmit} noValidate>
        <div style={field.group}>
          <label style={field.label}>Nome completo</label>
          <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} style={field.input} />
        </div>
        <div style={field.group}>
          <label style={field.label}>Email</label>
          <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} style={field.input} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div style={field.group}>
            <label style={field.label}>Password</label>
            <input required type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} style={field.input} />
          </div>
          <div style={field.group}>
            <label style={field.label}>Confirmar</label>
            <input required type="password" autoComplete="new-password" value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} style={field.input} />
          </div>
        </div>
        {error && <div style={field.error}>{error}</div>}
        <button type="submit" disabled={loading} style={{ ...field.primaryBtn, opacity: loading ? 0.7 : 1 }}>
          {loading ? "A criar conta..." : "Criar conta de administrador"}
        </button>
      </form>
    </AuthLayout>
  );
}
