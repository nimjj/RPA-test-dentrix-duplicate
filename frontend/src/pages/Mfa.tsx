import { FormEvent, useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api, ApiError, Me } from "../api";
import { Spinner, useApp, useUi } from "../ui";

export default function Mfa() {
  const ui = useUi();
  const { toast } = useApp();
  const navigate = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [gone, setGone] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Me>("/auth/me")
      .then(setMe)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) setGone(true);
      });
  }, []);

  if (gone) return <Navigate to="/login" replace />;
  if (!me) return <Spinner />;
  if (me.next !== "mfa") return <Navigate to={me.next === "location" ? "/select-location" : "/patients"} replace />;

  const step = me.mfa_step ?? "email";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const r = await api<{ next: string; mfa_step?: "email" | "sms" }>(`/auth/mfa/${step}`, { body: { code } });
      setCode("");
      if (r.next === "mfa") setMe({ ...me!, mfa_step: r.mfa_step, next: "mfa" });
      else navigate(r.next === "location" ? "/select-location" : "/patients", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "mfa_failed") {
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError("");
    try {
      await api("/auth/mfa/resend", { method: "POST", body: {} });
      toast(step === "email" ? "A new code was sent to your email." : "A new code was sent by text message.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  return (
    <div className="center-page">
      <div className="card">
        <h1>Verify your identity</h1>
        <p className="muted">
          {step === "email"
            ? "Step 1 of 2 · Enter the 6-digit code we emailed to your registered address."
            : "Step 2 of 2 · Enter the 6-digit code we sent by text message."}
        </p>
        <form onSubmit={submit}>
          <div className={ui.cls("field")}>
            <label htmlFor="mfa-code">{step === "email" ? "Email code" : "Text message code"}</label>
            <input
              id="mfa-code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
            />
          </div>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <button type="submit" className={ui.cls("primary")} disabled={busy || code.length !== 6}>
            Verify
          </button>{" "}
          <button type="button" className="link" onClick={resend}>
            Send a new code
          </button>
        </form>
      </div>
    </div>
  );
}
