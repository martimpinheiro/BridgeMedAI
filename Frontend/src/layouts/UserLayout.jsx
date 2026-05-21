import React from "react";
import AppShell from "../components/shell/AppShell.jsx";
import {
  IconDashboard,
  IconChat,
  IconStack,
  IconHistory,
  IconCheckList,
  IconGear,
} from "../components/ui/Icons.jsx";

const NAV = [
  {
    heading: "Visão geral",
    items: [
      { to: "/user/dashboard", label: "Início", icon: <IconDashboard size={16} /> },
    ],
  },
  {
    heading: "Trabalhar",
    items: [
      { to: "/user/chat", label: "Chatbot", icon: <IconChat size={16} /> },
      { to: "/user/templates", label: "Templates", icon: <IconStack size={16} /> },
      { to: "/user/validation", label: "Validação", icon: <IconCheckList size={16} /> },
    ],
  },
  {
    heading: "Pessoal",
    items: [
      { to: "/user/history", label: "Histórico", icon: <IconHistory size={16} /> },
      { to: "/user/profile", label: "Perfil", icon: <IconGear size={16} /> },
    ],
  },
];

export default function UserLayout() {
  return <AppShell role="user" navSections={NAV} />;
}
