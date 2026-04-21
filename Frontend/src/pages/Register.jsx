import React from "react";
import { Link } from "react-router-dom";
import AuthLayout from "../auth/AuthLayout.jsx";

export default function Register() {
  const cardBase = {
    display: "block",
    padding: "16px 18px",
    border: "1px solid var(--cream-edge)",
    borderRadius: 12,
    textDecoration: "none",
    color: "var(--ink)",
    background: "var(--paper)",
    marginBottom: 12,
    transition: "border-color 0.15s, transform 0.15s",
  };
  return (
    <AuthLayout
      title="Criar conta"
      subtitle="Escolha o tipo de conta que pretende registar."
      footer={
        <>
          Já tem conta?{" "}
          <Link to="/login" style={{ color: "var(--forest)", fontWeight: 600 }}>
            Iniciar sessão
          </Link>
        </>
      }
    >
      <Link to="/register/user" style={cardBase}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Utilizador geral</div>
        <div style={{ fontSize: 13, color: "var(--ink-muted)", lineHeight: 1.5 }}>
          Acesso imediato ao assistente de compliance — adequado para profissionais
          que consultam regulamentação de dispositivos médicos.
        </div>
      </Link>
      <Link to="/register/specialist" style={cardBase}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Especialista / Médico</div>
        <div style={{ fontSize: 13, color: "var(--ink-muted)", lineHeight: 1.5 }}>
          Requer validação manual por um administrador. Submete credenciais
          profissionais durante o registo.
        </div>
      </Link>
    </AuthLayout>
  );
}
