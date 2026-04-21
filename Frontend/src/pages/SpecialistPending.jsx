import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { apiJson } from "../auth/api.js";
import AuthLayout, { field } from "../auth/AuthLayout.jsx";

export default function SpecialistPending() {
  const { token, user, logout, login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    async function refresh() {
      try {
        const me = await apiJson("/auth/me", { token });
        if (!alive) return;
        if (me.status === "active") {
          login({
            token,
            expires_at: null,
            user: { id: me.id, email: me.email, full_name: me.full_name, role: me.role, status: me.status },
            specialist_profile: me.specialist_profile || null,
          });
          navigate("/app", { replace: true });
        } else if (me.status === "rejected") {
          navigate("/specialist/rejected", { replace: true });
        }
      } catch (err) {
        if (!alive) return;
        setError(err.message || "Erro ao verificar estado.");
      }
    }
    refresh();
    const t = setInterval(refresh, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [token, login, navigate]);

  return (
    <AuthLayout
      title="Conta em análise"
      subtitle="O seu registo de especialista está a aguardar aprovação por um administrador."
      footer={
        <button onClick={() => { logout(); navigate("/login", { replace: true }); }} style={{ ...field.ghostBtn, marginTop: 0 }}>
          Terminar sessão
        </button>
      }
    >
      <div style={{ fontSize: 14, color: "var(--ink-muted)", lineHeight: 1.6 }}>
        <p style={{ marginTop: 0 }}>
          Olá <strong style={{ color: "var(--ink)" }}>{user?.full_name}</strong>. Submeteu as credenciais e estas estão a ser revistas.
        </p>
        <p>
          Será notificado quando a sua conta for aprovada ou caso sejam pedidos mais documentos. Esta
          página verifica automaticamente o estado a cada 15 segundos.
        </p>
      </div>
      {error && <div style={field.error}>{error}</div>}
    </AuthLayout>
  );
}
