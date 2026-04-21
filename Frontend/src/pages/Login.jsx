import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiJson } from "../auth/api.js";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";
import { defaultRouteFor } from "../auth/ProtectedRoute.jsx";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const payload = await apiJson("/auth/login", {
        method: "POST",
        body: { email: email.trim(), password },
      });
      login(payload);
      const dest = location.state?.from?.pathname || defaultRouteFor(payload.user);
      navigate(dest, { replace: true });
    } catch (err) {
      setError(err.message || "Não foi possível iniciar sessão.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Iniciar sessão"
      subtitle="Introduza as suas credenciais para aceder à plataforma."
      footer={
        <>
          Ainda não tem conta?{" "}
          <Link to="/register" style={{ color: "var(--forest)", fontWeight: 600 }}>
            Registar-se
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate>
        <div style={field.group}>
          <label htmlFor="email" style={field.label}>Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={field.input}
          />
        </div>
        <div style={field.group}>
          <label htmlFor="password" style={field.label}>Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={field.input}
          />
        </div>
        {error && <div style={field.error}>{error}</div>}
        <button type="submit" disabled={loading} style={{ ...field.primaryBtn, opacity: loading ? 0.7 : 1 }}>
          {loading ? "A autenticar..." : "Entrar"}
        </button>
      </form>
    </AuthLayout>
  );
}
