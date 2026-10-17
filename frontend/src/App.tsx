import { Loader2 } from "lucide-react";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { useAuth } from "./lib/auth";
import Login from "./pages/Login";

// Each page is its own chunk, so the first load only fetches what the current page needs.
const Register = lazy(() => import("./pages/Register"));
const ForgotPassword = lazy(() => import("./pages/PasswordPages").then((m) => ({ default: m.ForgotPassword })));
const ResetPassword = lazy(() => import("./pages/PasswordPages").then((m) => ({ default: m.ResetPassword })));
const AcceptInvite = lazy(() => import("./pages/PasswordPages").then((m) => ({ default: m.AcceptInvite })));
const Onboarding = lazy(() => import("./pages/Onboarding"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Copilot = lazy(() => import("./pages/Copilot"));
const CashFlow = lazy(() => import("./pages/CashFlow"));
const Financing = lazy(() => import("./pages/Financing"));
const Approvals = lazy(() => import("./pages/Approvals"));
const Data = lazy(() => import("./pages/Data"));
const Reports = lazy(() => import("./pages/Reports"));
const Team = lazy(() => import("./pages/Team"));
const Audit = lazy(() => import("./pages/Audit"));
const Settings = lazy(() => import("./pages/Settings"));

function Spinner() {
  return (
    <div className="grid min-h-[50dvh] place-items-center text-muted">
      <Loader2 className="size-6 animate-spin" aria-label="Loading" />
    </div>
  );
}

function PublicRoutes() {
  return (
    <Routes>
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/accept-invite" element={<AcceptInvite />} />
      <Route path="*" element={<Login />} />
    </Routes>
  );
}

export default function App() {
  const { user, ready } = useAuth();
  if (!ready) return <Spinner />;
  const onboarding = user?.business && user.business.onboardingStatus !== "complete";
  return (
    <BrowserRouter>
      <Suspense fallback={<Spinner />}>
        {!user ? <PublicRoutes /> : onboarding ? (
          // Setup has its own full-screen layout: the app navigation would only lead back here.
          <Routes>
            <Route path="*" element={<Onboarding />} />
          </Routes>
        ) : (
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<Dashboard />} />
              <Route path="copilot" element={<Copilot />} />
              <Route path="cash-flow" element={<CashFlow />} />
              <Route path="financing" element={<Financing />} />
              <Route path="approvals" element={<Approvals />} />
              <Route path="reports" element={<Reports />} />
              <Route path="data" element={<Data />} />
              <Route path="team" element={<Team />} />
              <Route path="audit" element={<Audit />} />
              <Route path="settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        )}
      </Suspense>
    </BrowserRouter>
  );
}
