import React, { useEffect } from "react";
import ChatbotApp from "../ChatbotApp.jsx";
import "./embedded-chat.css";

/**
 * EmbeddedChatbot — wrapper que renderiza o ChatbotApp dentro do UserLayout
 * (shell com sidebar nova) sem duplicação visual.
 *
 * O ChatbotApp original tem layout próprio: aside escuro + grid + sidebar de
 * conversas + brand + footer com user/logout. Quando embedded no nosso shell,
 * essas peças sobrepõem-se ao shell e ficam confusas.
 *
 * Estratégia: envolver com uma classe CSS que:
 *   - esconde a aside interna inteira (já temos sidebar do shell)
 *   - força o main a ocupar a coluna inteira
 *   - ajusta height ao espaço disponível (descontando topbar)
 *   - aplica auto-resize ao textarea de input
 *
 * As "conversas" antigas continuam acessíveis via /user/history (que mostra
 * o mesmo traceability + agrupamento por dia).
 */
export default function EmbeddedChatbot() {
  // Auto-resize do textarea — observamos todos os textareas dentro do
  // container e damos-lhes comportamento de auto-grow. Mais robusto que
  // tentar passar ref ao ChatbotApp interno.
  useEffect(() => {
    const root = document.querySelector(".embedded-chat");
    if (!root) return;

    const resize = (el) => {
      el.style.height = "auto";
      // cap em 320px para não tomar conta da tela toda
      el.style.height = Math.min(el.scrollHeight, 320) + "px";
    };

    const onInput = (ev) => {
      const target = ev.target;
      if (target && target.tagName === "TEXTAREA") {
        resize(target);
      }
    };

    // tamanho inicial dos textareas já existentes
    root.querySelectorAll("textarea").forEach(resize);

    root.addEventListener("input", onInput);
    // refresh periódico para apanhar textareas recém-criados (e.g. quando
    // muda de conversa)
    const interval = setInterval(() => {
      root.querySelectorAll("textarea").forEach(resize);
    }, 1500);

    return () => {
      root.removeEventListener("input", onInput);
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="embedded-chat">
      <ChatbotApp />
    </div>
  );
}
