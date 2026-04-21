import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext.jsx";
import ProtectedRoute, { defaultRouteFor } from "./auth/ProtectedRoute.jsx";

import ChatbotApp from "./pages/ChatbotApp.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import RegisterUser from "./pages/RegisterUser.jsx";
import RegisterSpecialist from "./pages/RegisterSpecialist.jsx";
import SpecialistPending from "./pages/SpecialistPending.jsx";
import SpecialistRejected from "./pages/SpecialistRejected.jsx";
import InviteRegister from "./pages/InviteRegister.jsx";
import AdminPanel from "./pages/AdminPanel.jsx";

function RootRedirect() {
  const { user } = useAuth();
  return <Navigate to={user ? defaultRouteFor(user) : "/login"} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<RootRedirect />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/register/user" element={<RegisterUser />} />
          <Route path="/register/specialist" element={<RegisterSpecialist />} />
          <Route path="/invite/:token" element={<InviteRegister />} />
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
          <Route
            path="/app"
            element={
              <ProtectedRoute roles={["user", "specialist", "admin"]}>
                <ChatbotApp />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin"
            element={
              <ProtectedRoute roles={["admin"]}>
                <AdminPanel />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<RootRedirect />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
