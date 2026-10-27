import { FormEvent, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, FLASH_KEY } from "../api";
import { useApp, useUi } from "../ui";

declare global {
  interface Window {
    grecaptcha?: any;
    __ledgerlabCaptchaReady?: () => void;
  }
}

function loadRecaptcha(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.grecaptcha?.enterprise?.render) return resolve();
    window.__ledgerlabCaptchaReady = () => resolve();
    const s = document.createElement("script");
    s.src = "https://www.google.com/recaptcha/enterprise.js?onload=__ledgerlabCaptchaReady&render=explicit";
    s.async = true;
    s.defer = true;
    s.onerror = () => reject(new Error("Could not load reCAPTCHA"));
    document.head.appendChild(s);
  });
}

function Captcha({ siteKey, onToken }: { siteKey: string; onToken: (t: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const widget = useRef<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    loadRecaptcha()
      .then(() => {
        window.grecaptcha.enterprise.ready(() => {
          if (cancelled || !box.current || widget.current !== null) return;
          widget.current = window.grecaptcha.enterprise.render(box.current, {
            sitekey: siteKey,
            callback: (token: string) => onToken(token),
            "expired-callback": () => onToken(""),
            "error-callback": () => onToken(""),
          });
        });
      })
      .catch((e) => setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [siteKey, onToken]);

  return (
    <div className="captcha">
      <div ref={box} />
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  );
}

export function resetCaptcha() {
  try {
    window.grecaptcha?.enterprise?.reset();
  } catch {
    /* widget not rendered */
  }
}

export default function Login() {
  const ui = useUi();
  const { config } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const dev = params.get("dev") === "1";

  const [step, setStep] = useState<1 | 2>(1);
  const [organization, setOrganization] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [captchaRequired, setCaptchaRequired] = useState(false);
  const [siteKey, setSiteKey] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try {
      const msg = sessionStorage.getItem(FLASH_KEY);
      if (msg) {
        setFlash(msg);
        sessionStorage.removeItem(FLASH_KEY);
      }
    } catch {
      /* storage unavailable */
    }
  }, []);

  async function onContinue(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const r = await api<{ captcha_required: boolean; site_key: string }>("/auth/identify", {
        body: { organization, username },
      });
      setCaptchaRequired(r.captcha_required);
      setSiteKey(r.site_key || config?.recaptcha_site_key || "");
      setToken("");
      setStep(2);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onLogin(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const r = await api<{ next: "mfa" | "location" | "app" }>("/auth/login", {
        body: { organization, username, password, captcha_token: captchaRequired ? token : undefined },
      });
      const from = (location.state as { from?: string } | null)?.from;
      if (r.next === "mfa") navigate("/login/mfa", { replace: true });
      else if (r.next === "location") navigate("/select-location", { replace: true });
      else navigate(from && from !== "/login" ? from : dev ? "/dev/settings" : "/patients", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setPassword("");
      if (captchaRequired) {
        setToken("");
        resetCaptcha();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-page">
      <div className="card">
        <h1>LedgerLab</h1>
        <p className="muted">Practice management sign in</p>
        {flash && (
          <p role="alert" className="info">
            {flash}
          </p>
        )}
        {step === 1 ? (
          <form onSubmit={onContinue}>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("organization")}>{ui.t("organization")}</label>
              <input
                id={ui.id("organization")}
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
                autoComplete="organization"
                autoFocus
              />
            </div>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("username")}>{ui.t("username")}</label>
              <input
                id={ui.id("username")}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
            </div>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button type="submit" className={ui.cls("primary")} disabled={busy || !organization.trim() || !username.trim()}>
              {ui.t("continue")}
            </button>
          </form>
        ) : (
          <form onSubmit={onLogin}>
            <p className="muted">
              {organization} / <strong>{username}</strong>{" "}
              <button type="button" className="link" onClick={() => { setStep(1); setError(""); setPassword(""); }}>
                Not you?
              </button>
            </p>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("password")}>{ui.t("password")}</label>
              <input
                id={ui.id("password")}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                autoFocus
              />
            </div>
            {captchaRequired && <Captcha siteKey={siteKey} onToken={setToken} />}
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button
              type="submit"
              className={ui.cls("primary")}
              disabled={busy || !password || (captchaRequired && !token)}
            >
              {ui.t("logIn")}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
