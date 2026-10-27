import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { FLASH_KEY, handlers } from "./api";
import { Spinner, useApp } from "./ui";
import Layout, { RequireAuth } from "./components/Layout";
import Login from "./pages/Login";
import Mfa from "./pages/Mfa";
import SelectLocation from "./pages/SelectLocation";
import Patients from "./pages/Patients";
import Ledger from "./pages/Ledger";
import DevSettings from "./pages/DevSettings";
import DevAudit from "./pages/DevAudit";
import DevSms from "./pages/DevSms";
import Maintenance from "./pages/Maintenance";

export default function App() {
  const { config, refreshConfig, maintenance, setMaintenance } = useApp();
  const navigate = useNavigate();
  const location = useLocation();

  // Session ended by the server (idle timeout / bot detection): go to login with a message.
  useEffect(() => {
    handlers.onSessionEnded = (_code, message) => {
      try {
        sessionStorage.setItem(FLASH_KEY, message);
      } catch {
        /* storage unavailable */
      }
      navigate("/login", { replace: true });
    };
    handlers.onMaintenance = () => setMaintenance(true);
    return () => {
      handlers.onSessionEnded = undefined;
      handlers.onMaintenance = undefined;
    };
  }, [navigate, setMaintenance]);

  // Chaos switches can change at any time: re-read them on every navigation.
  useEffect(() => {
    void refreshConfig();
  }, [location.pathname, refreshConfig]);

  // A maintenance flag set by a 503 is cleared once the outage is over.
  useEffect(() => {
    if (config && !config.outage) setMaintenance(false);
  }, [config, setMaintenance]);

  // Slow mode: random 0.5 - 4 s page transitions with a spinner.
  const [transitioning, setTransitioning] = useState(false);
  useEffect(() => {
    if (!config?.slow_mode) {
      setTransitioning(false);
      return;
    }
    setTransitioning(true);
    const timer = setTimeout(() => setTransitioning(false), 500 + Math.random() * 3500);
    return () => clearTimeout(timer);
    // only on navigation
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  if (!config) return <Spinner />;

  const devArea = location.pathname.startsWith("/dev");
  const devLogin = location.pathname === "/login" && new URLSearchParams(location.search).get("dev") === "1";
  if ((config.outage || maintenance) && !devArea && !devLogin) return <Maintenance />;
  if (transitioning) return <Spinner />;

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/login/mfa" element={<Mfa />} />
      <Route path="/dev/sms" element={<DevSms />} />
      <Route element={<RequireAuth />}>
        <Route path="/select-location" element={<SelectLocation />} />
        <Route element={<Layout />}>
          <Route path="/patients" element={<Patients />} />
          <Route path="/patients/:account/ledger" element={<Ledger />} />
          <Route path="/dev/settings" element={<DevSettings />} />
          <Route path="/dev/audit" element={<DevAudit />} />
        </Route>
      </Route>
      <Route path="/maintenance" element={<Maintenance />} />
      <Route path="*" element={<Navigate to="/patients" replace />} />
    </Routes>
  );
}
