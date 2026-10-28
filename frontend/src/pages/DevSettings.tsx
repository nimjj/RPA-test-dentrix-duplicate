import { ReactNode, useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { Spinner, useApp, useUi } from "../ui";

type Settings = {
  captcha_mode: string;
  mfa_sms_step: boolean;
  idle_timeout_minutes: number;
  bot_detection: boolean;
  bot_max_requests_per_min: number;
  bot_min_action_ms: number;
  bot_flag_forces_mfa: boolean;
  chaos_slow: boolean;
  chaos_outage: boolean;
  chaos_ui_changed: boolean;
};
type DevUser = {
  id: number;
  username: string;
  full_name: string;
  role: string;
  status: string;
  flagged: boolean;
  devices: number;
  locations: string[];
};
type DevLocation = {
  id: number;
  name: string;
  lock_before_date: string | null;
  payment_types: { id: number; code: string; label: string }[];
};
type Payload = {
  settings: Settings;
  captcha_provider: string;
  organization: { name: string; trusted_ips: string[] };
  locations: DevLocation[];
  users: DevUser[];
};

export default function DevSettings() {
  const ui = useUi();
  const { toast, refreshConfig } = useApp();
  const navigate = useNavigate();
  const [data, setData] = useState<Payload | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [ips, setIps] = useState("");
  const [locs, setLocs] = useState<DevLocation[]>([]);
  const [confirmReset, setConfirmReset] = useState(false);
  const [error, setError] = useState("");

  const adopt = useCallback((p: Payload) => {
    setData(p);
    setSettings(p.settings);
    setIps(p.organization.trusted_ips.join("\n"));
    setLocs(p.locations);
  }, []);

  useEffect(() => {
    api<Payload>("/dev/settings")
      .then(adopt)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load settings."));
  }, [adopt]);

  async function run<T>(fn: () => Promise<T>, ok: string, after?: (r: T) => void) {
    setError("");
    try {
      const r = await fn();
      after?.(r);
      toast(ok);
      void refreshConfig();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Something went wrong.";
      setError(msg);
      toast(msg, "error");
    }
  }

  if (error && !data) return <p role="alert" className="error">{error}</p>;
  if (!data || !settings) return <Spinner />;

  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setSettings({ ...settings, [k]: v });
  const saveSettings = (patch: Partial<Settings>, ok: string) =>
    run(() => api<Payload>("/dev/settings", { method: "PUT", body: patch }), ok, adopt);

  return (
    <section className="dev">
      <h1>Dev Settings</h1>
      <p className="muted">Changes apply immediately, no restart needed. Test target only; synthetic data.</p>
      {error && <p role="alert" className="error">{error}</p>}

      <Card title="Login security">
        <div className={ui.cls("field")}>
          <label htmlFor="captcha-mode">CAPTCHA mode</label>
          <select id="captcha-mode" value={settings.captcha_mode} onChange={(e) => set("captcha_mode", e.target.value)}>
            <option value="never">never</option>
            <option value="new_device">new_device (no recognized device cookie)</option>
            <option value="after_flag">after_flag (after bot detection)</option>
            <option value="always">always</option>
          </select>
          <small className="muted">
            Provider (from .env): <strong>{data.captcha_provider}</strong>
            {data.captcha_provider === "off" && " — no CAPTCHA widget is shown whatever the mode."}
            {data.captcha_provider === "test" && " — using Google's official localhost test keys."}
          </small>
        </div>
        <Check label="Require a second MFA code by SMS (MFA_SMS_STEP)" checked={settings.mfa_sms_step} onChange={(v) => set("mfa_sms_step", v)} />
        <Num label="Idle timeout (minutes)" value={settings.idle_timeout_minutes} onChange={(v) => set("idle_timeout_minutes", v)} />
        <button
          type="button"
          className={ui.cls("primary")}
          onClick={() =>
            saveSettings(
              { captcha_mode: settings.captcha_mode, mfa_sms_step: settings.mfa_sms_step, idle_timeout_minutes: settings.idle_timeout_minutes },
              "Login security saved.",
            )
          }
        >
          Save login security
        </button>
      </Card>

      <Card title="Bot detection">
        <Check label="Bot detection on" checked={settings.bot_detection} onChange={(v) => set("bot_detection", v)} />
        <Num label="Max API requests per minute" value={settings.bot_max_requests_per_min} onChange={(v) => set("bot_max_requests_per_min", v)} />
        <Num label="Min ms between form submissions (6 fast ones in a row flag the session)" value={settings.bot_min_action_ms} onChange={(v) => set("bot_min_action_ms", v)} />
        <Check label="A flagged account must also pass MFA at next login" checked={settings.bot_flag_forces_mfa} onChange={(v) => set("bot_flag_forces_mfa", v)} />
        <button
          type="button"
          className={ui.cls("primary")}
          onClick={() =>
            saveSettings(
              {
                bot_detection: settings.bot_detection,
                bot_max_requests_per_min: settings.bot_max_requests_per_min,
                bot_min_action_ms: settings.bot_min_action_ms,
                bot_flag_forces_mfa: settings.bot_flag_forces_mfa,
              },
              "Bot detection saved.",
            )
          }
        >
          Save bot detection
        </button>
      </Card>

      <Card title="Trusted IP addresses">
        <p className="muted">
          {data.organization.name}. One IP or CIDR range per line. Logins from these addresses skip MFA.
        </p>
        <div className={ui.cls("field")}>
          <label htmlFor="trusted-ips">Trusted IPs</label>
          <textarea id="trusted-ips" rows={4} value={ips} onChange={(e) => setIps(e.target.value)} />
        </div>
        <button
          type="button"
          className={ui.cls("primary")}
          onClick={() =>
            run(
              () =>
                api<Payload>("/dev/org/trusted-ips", {
                  method: "PUT",
                  body: { ips: ips.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean) },
                }),
              "Trusted IPs saved.",
              adopt,
            )
          }
        >
          Save trusted IPs
        </button>
      </Card>

      <Card title="Chaos switches">
        <p className="muted">Applied the moment you tick them.</p>
        <Check
          label="Slow mode: random 0.5–4 s delays on API responses and page transitions"
          checked={settings.chaos_slow}
          onChange={(v) => saveSettings({ chaos_slow: v }, `Slow mode ${v ? "on" : "off"}.`)}
        />
        <Check
          label="Outage mode: HTTP 503 and a maintenance page everywhere except Dev Settings"
          checked={settings.chaos_outage}
          onChange={(v) => saveSettings({ chaos_outage: v }, `Outage mode ${v ? "on" : "off"}.`)}
        />
        <Check
          label="UI changed mode: renamed labels, new element ids and classes, moved Save button"
          checked={settings.chaos_ui_changed}
          onChange={(v) => saveSettings({ chaos_ui_changed: v }, `UI changed mode ${v ? "on" : "off"}.`)}
        />
      </Card>

      {locs.map((l, li) => (
        <Card key={l.id} title={`Location: ${l.name}`}>
          <div className={ui.cls("field")}>
            <label htmlFor={`lock-${l.id}`}>Lock transactions before</label>
            <input
              id={`lock-${l.id}`}
              type="date"
              value={l.lock_before_date ?? ""}
              onChange={(e) => setLocs(locs.map((x, i) => (i === li ? { ...x, lock_before_date: e.target.value || null } : x)))}
            />
            <small className="muted">Payments dated before this day are rejected. Empty = no lock.</small>
          </div>
          <fieldset>
            <legend>Payment type names</legend>
            {l.payment_types.map((t, ti) => (
              <div className={ui.cls("field")} key={t.id}>
                <label htmlFor={`pt-${t.id}`}>{t.code}</label>
                <input
                  id={`pt-${t.id}`}
                  value={t.label}
                  onChange={(e) =>
                    setLocs(
                      locs.map((x, i) =>
                        i === li ? { ...x, payment_types: x.payment_types.map((y, j) => (j === ti ? { ...y, label: e.target.value } : y)) } : x,
                      ),
                    )
                  }
                />
              </div>
            ))}
          </fieldset>
          <button
            type="button"
            className={ui.cls("primary")}
            onClick={() =>
              run(
                () =>
                  api<Payload>(`/dev/locations/${l.id}`, {
                    method: "PUT",
                    body: {
                      lock_before_date: l.lock_before_date,
                      payment_types: l.payment_types.map((t) => ({ id: t.id, label: t.label })),
                    },
                  }),
                `${l.name} saved.`,
                adopt,
              )
            }
          >
            Save {l.name}
          </button>
        </Card>
      ))}

      <Card title="Users">
        <table className={ui.cls("table")}>
          <thead>
            <tr>
              <th scope="col">Username</th>
              <th scope="col">Role</th>
              <th scope="col">Locations</th>
              <th scope="col">Status</th>
              <th scope="col">Bot flag</th>
              <th scope="col">Devices</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{u.role}</td>
                <td>{u.locations.join(", ")}</td>
                <td>{u.status}</td>
                <td>{u.flagged ? "flagged" : "—"}</td>
                <td>{u.devices}</td>
                <td className="actions">
                  <button
                    type="button"
                    className={ui.cls("secondary")}
                    disabled={u.status === "active"}
                    onClick={() =>
                      run(() => api<{ users: DevUser[] }>(`/dev/users/${u.id}/reactivate`, { method: "POST", body: {} }), `${u.username} reactivated.`, (r) =>
                        setData({ ...data, users: r.users }),
                      )
                    }
                  >
                    Reactivate
                  </button>{" "}
                  <button
                    type="button"
                    className={ui.cls("secondary")}
                    disabled={u.devices === 0}
                    onClick={() =>
                      run(() => api<{ users: DevUser[] }>(`/dev/users/${u.id}/clear-devices`, { method: "POST", body: {} }), `Devices cleared for ${u.username}.`, (r) =>
                        setData({ ...data, users: r.users }),
                      )
                    }
                  >
                    Clear devices
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Reset">
        {!confirmReset ? (
          <button type="button" className="btn-danger" onClick={() => setConfirmReset(true)}>
            Reset database to seed data
          </button>
        ) : (
          <div role="group" aria-label="Confirm reset">
            <p>This wipes every payment, device, audit row and setting, then logs everyone out. Continue?</p>
            <button
              type="button"
              className="btn-danger"
              onClick={() =>
                run(() => api("/dev/reset-db", { method: "POST", body: {} }), "Database reset. Please log in again.", () =>
                  navigate("/login?dev=1", { replace: true }),
                )
              }
            >
              Yes, reset everything
            </button>{" "}
            <button type="button" className={ui.cls("secondary")} onClick={() => setConfirmReset(false)}>
              Cancel
            </button>
          </div>
        )}
      </Card>
    </section>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function Num({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  const ui = useUi();
  return (
    <div className={ui.cls("field")}>
      <label>
        {label}
        <input type="number" min={0} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      </label>
    </div>
  );
}
