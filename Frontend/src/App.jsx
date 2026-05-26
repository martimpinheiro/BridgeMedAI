import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext.jsx";
import ProtectedRoute, { defaultRouteFor } from "./auth/ProtectedRoute.jsx";

// Public pages
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import RegisterUser from "./pages/RegisterUser.jsx";
import RegisterSpecialist from "./pages/RegisterSpecialist.jsx";
import InviteRegister from "./pages/InviteRegister.jsx";

// Specialist holding pages (pending/rejected)
import SpecialistPending from "./pages/SpecialistPending.jsx";
import SpecialistRejected from "./pages/SpecialistRejected.jsx";

// Layouts (shells)
import AdminLayout from "./layouts/AdminLayout.jsx";
import SpecialistLayout from "./layouts/SpecialistLayout.jsx";
import UserLayout from "./layouts/UserLayout.jsx";

// Dashboards (Fase 1+2)
import AdminDashboard from "./pages/dashboards/AdminDashboard.jsx";
import SpecialistDashboard from "./pages/dashboards/SpecialistDashboard.jsx";
import UserDashboard from "./pages/dashboards/UserDashboard.jsx";

// Admin sub-pages (Fase 3)
import AdminSpecialists from "./pages/admin/AdminSpecialists.jsx";
import AdminUsers from "./pages/admin/AdminUsers.jsx";
import AdminInvites from "./pages/admin/AdminInvites.jsx";
import AdminMatrix from "./pages/admin/AdminMatrix.jsx";
import AdminLogs from "./pages/admin/AdminLogs.jsx";
import AdminSettings from "./pages/admin/AdminSettings.jsx";

// Specialist sub-pages (Fase 4)
import SpecialistQueue from "./pages/specialist/SpecialistQueue.jsx";
import SpecialistValidation from "./pages/specialist/SpecialistValidation.jsx";
import SpecialistMatrix from "./pages/specialist/SpecialistMatrix.jsx";
import SpecialistHistory from "./pages/specialist/SpecialistHistory.jsx";
import SpecialistProfile from "./pages/specialist/SpecialistProfile.jsx";

// User sub-pages (Fase 5)
import UserTemplates from "./pages/user/UserTemplates.jsx";
import UserHistory from "./pages/user/UserHistory.jsx";
import UserValidation from "./pages/user/UserValidation.jsx";
import UserProfile from "./pages/user/UserProfile.jsx";
import EmbeddedChatbot from "./pages/user/EmbeddedChatbot.jsx";

function RootRedirect() {
  const { user } = useAuth();
  return <Navigate to={user ? defaultRouteFor(user) : "/login"} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* ----------------- Public ----------------- */}
          <Route path="/" element={<RootRedirect />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/register/user" element={<RegisterUser />} />
          <Route path="/register/specialist" element={<RegisterSpecialist />} />
          <Route path="/invite/:token" element={<InviteRegister />} />

          {/* ----------------- Specialist holding states ----------------- */}
          <Route
            path="/specialist/pending"
            element={
              <ProtectedRoute roles={["specialist"]} requireActive={false}>
                <SpecialistPending />
              </ProtectedRoute>
            }
          />
          <Route
            path="/specialist/rejected"
            element={
              <ProtectedRoute roles={["specialist"]} requireActive={false}>
                <SpecialistRejected />
              </ProtectedRoute>
            }
          />

          {/* ----------------- ADMIN ----------------- */}
          <Route
            element={
              <ProtectedRoute roles={["admin"]}>
                <AdminLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />
            <Route path="/admin/dashboard" element={<AdminDashboard />} />
            <Route path="/admin/specialists" element={<AdminSpecialists />} />
            <Route path="/admin/users" element={<AdminUsers />} />
            <Route path="/admin/invites" element={<AdminInvites />} />
            <Route path="/admin/matrix" element={<AdminMatrix />} />
            <Route path="/admin/logs" element={<AdminLogs />} />
            <Route path="/admin/settings" element={<AdminSettings />} />
          </Route>

          {/* ----------------- SPECIALIST ----------------- */}
          <Route
            element={
              <ProtectedRoute roles={["specialist"]}>
                <SpecialistLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/specialist" element={<Navigate to="/specialist/dashboard" replace />} />
            <Route path="/specialist/dashboard" element={<SpecialistDashboard />} />
            <Route path="/specialist/queue" element={<SpecialistQueue />} />
            <Route path="/specialist/validation" element={<SpecialistValidation />} />
            <Route path="/specialist/matrix" element={<SpecialistMatrix />} />
            <Route path="/specialist/history" element={<SpecialistHistory />} />
            <Route path="/specialist/profile" element={<SpecialistProfile />} />
          </Route>

          {/* ----------------- USER (Cliente) ----------------- */}
          <Route
            element={
              <ProtectedRoute roles={["user"]}>
                <UserLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/user" element={<Navigate to="/user/dashboard" replace />} />
            <Route path="/user/dashboard" element={<UserDashboard />} />
            <Route path="/user/chat" element={<EmbeddedChatbot />} />
            <Route path="/user/templates" element={<UserTemplates />} />
            <Route path="/user/history" element={<UserHistory />} />
            <Route path="/user/validation" element={<UserValidation />} />
            <Route path="/user/profile" element={<UserProfile />} />
          </Route>

          {/* ----------------- Backward compatibility ----------------- */}
          <Route path="/app" element={<RootRedirect />} />

          {/* ----------------- Fallback ----------------- */}
          <Route path="*" element={<RootRedirect />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

/* Placeholder simples para rotas que ainda não estão construídas (Fases 3-5) */
function UnderConstruction({ title }) {
  return (
    <>
      <header
        style={{
          padding: "28px 0 22px",
          borderBottom: "1px solid rgba(21,42,32,0.1)",
          marginBottom: 28,
        }}
      >
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: 10,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: "var(--ink-faded)",
            marginBottom: 6,
          }}
        >
          Em construção
        </div>
        <h1
          style={{
            fontFamily: "var(--display)",
            fontSize: "clamp(28px, 3.4vw, 40px)",
            fontWeight: 400,
            color: "var(--forest-deep)",
            margin: 0,
            letterSpacing: "-0.015em",
          }}
        >
          {title}
        </h1>
      </header>
      <div
        style={{
          textAlign: "center",
          padding: "60px 16px",
          border: "1px dashed rgba(21,42,32,0.15)",
          borderRadius: "var(--r-md)",
          background: "rgba(250,247,236,0.5)",
        }}
      >
        <p
          style={{
            fontFamily: "var(--display)",
            fontStyle: "italic",
            fontSize: 16,
            color: "var(--ink-muted)",
            maxWidth: "44ch",
            margin: "0 auto",
            lineHeight: 1.55,
          }}
        >
          Esta página estará disponível numa fase seguinte do redesenho. A
          arquitetura já está pronta a recebê-la — falta apenas o conteúdo.
        </p>
      </div>
    </>
  );
}
