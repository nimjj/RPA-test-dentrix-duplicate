import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError, Me } from "../api";
import { Spinner, useUi } from "../ui";

type MeCtx = { me: Me; reload: () => Promise<void> };
const MeContext = createContext<MeCtx>(null as unknown as MeCtx);
export const useMe = () => useContext(MeContext);

/** Loads /auth/me and sends the user to the right step of the login flow. */
export function RequireAuth() {
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState<ApiError | null>(null);
  const location = useLocation();

  const load = useCallback(async () => {
    try {
      setMe(await api<Me>("/auth/me"));
    } catch (e) {
      if (e instanceof ApiError) setFailed(e);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    if (failed.code === "idle_timeout" || failed.code === "bot_detected") return <Spinner />; // handler redirects
    const dev = location.pathname.startsWith("/dev") ? "?dev=1" : "";
    return <Navigate to={`/login${dev}`} replace state={{ from: location.pathname }} />;
  }
  if (!me) return <Spinner />;
  if (me.next === "mfa") return <Navigate to="/login/mfa" replace />;
  if (me.next === "location" && location.pathname !== "/select-location") return <Navigate to="/select-location" replace />;
  return (
    <MeContext.Provider value={{ me, reload: load }}>
      <Outlet />
    </MeContext.Provider>
  );
}

export default function Layout() {
  const { me } = useMe();
  const ui = useUi();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    try {
      await api("/auth/logout", { method: "POST", body: {} });
    } finally {
      navigate("/login", { replace: true });
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/patients" className="brand">
          LedgerLab
        </Link>
        <nav aria-label="Main">
          <Link to="/patients">Patients</Link>
          {me.user.role === "admin" && (
            <>
              <Link to="/dev/settings">Dev Settings</Link>
              <Link to="/dev/audit">Audit Log</Link>
              <Link to="/dev/sms">SMS Inbox</Link>
            </>
          )}
        </nav>
        <div className="who">
          <span>
            {me.organization.name}
            {me.location ? ` · ${me.location.name}` : ""}
          </span>
          <span>{me.user.full_name}</span>
          {me.locations.length > 1 && <Link to="/select-location">Switch location</Link>}
          <button type="button" className={ui.cls("secondary")} onClick={logout} disabled={busy}>
            {ui.t("logOut")}
          </button>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
