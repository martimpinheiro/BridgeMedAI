import React from "react";
import AppShell from "../components/shell/AppShell.jsx";
import {
  IconDashboard,
  IconInbox,
  IconCheckList,
  IconScroll,
  IconHistory,
  IconGear,
} from "../components/ui/Icons.jsx";

const NAV = [
  {
    heading: "Visão geral",
    items: [
      { to: "/specialist/dashboard", label: "Dashboard", icon: <IconDashboard size={16} /> },
    ],
  },
  {
    heading: "Análise",
    items: [
      { to: "/specialist/queue", label: "Fila de revisão", icon: <IconInbox size={16} /> },
      { to: "/specialist/validation", label: "Validação", icon: <IconCheckList size={16} /> },
      { to: "/specialist/matrix", label: "Matriz regulatória", icon: <IconScroll size={16} /> },
    ],
  },
  {
    heading: "Pessoal",
    items: [
      { to: "/specialist/history", label: "Histórico", icon: <IconHistory size={16} /> },
      { to: "/specialist/profile", label: "Perfil", icon: <IconGear size={16} /> },
    ],
  },
];

export default function SpecialistLayout() {
  return <AppShell role="specialist" navSections={NAV} />;
}
