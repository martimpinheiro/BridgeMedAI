import React, { useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiJson } from "../auth/api.js";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";
import { defaultRouteFor } from "../auth/ProtectedRoute.jsx";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const banner = useMemo(() => {
    const r = searchParams.get("registered");
    if (r === "specialist") {
      return {
        title: "Candidatura submetida ✓",
        body: "A tua conta de especialista foi criada em estado pendente. Vais poder iniciar sessão assim que um administrador aprovar a candidatura.",
      };
    }
    if (r === "user") {
      return {
        title: "Conta criada ✓",
        body: "Já podes iniciar sessão com o teu email e password.",
      };
    }
    return null;
  }, [searchParams]);

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
      {banner && (
        <div style={{
          marginBottom: 18,
          padding: "12px 14px",
          background: "rgba(47,122,61,0.08)",
          border: "1px solid rgba(47,122,61,0.25)",
          borderLeft: "3px solid var(--check)",
          borderRadius: 8,
          color: "var(--forest-deep)",
        }}>
          <div style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--check)",
            marginBottom: 4,
          }}>
            {banner.title}
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.55, color: "var(--ink-muted)" }}>
            {banner.body}
          </div>
        </div>
      )}

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
