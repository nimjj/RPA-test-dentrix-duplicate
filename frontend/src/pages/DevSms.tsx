import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { Spinner } from "../ui";

type Msg = { id: number; user: string; phone: string; code: string; created_at: string };

/** Dev SMS Inbox: there is no real SMS, the second MFA code lands here. Open on purpose. */
export default function DevSms() {
  const [user, setUser] = useState("");
  const [applied, setApplied] = useState("");
  const [msgs, setMsgs] = useState<Msg[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (u: string) => {
    setError("");
    try {
      const r = await api<{ messages: Msg[] }>("/dev/sms", { query: { user: u } });
      setMsgs(r.messages);
      setApplied(u);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load messages.");
    }
  }, []);

  useEffect(() => {
    void load("");
  }, [load]);

  function filter(e: FormEvent) {
    e.preventDefault();
    void load(user.trim());
  }

  return (
    <div className="plain-page">
      <p>
        <Link to="/login">← Login</Link>
      </p>
      <h1>Dev SMS Inbox</h1>
      <p className="muted">
        Text messages the app would have sent. A bot can read the newest one at{" "}
        <code>GET /api/dev/sms/latest?user=&lt;username&gt;</code>.
      </p>
      <form onSubmit={filter} className="inline-form">
        <div className="field">
          <label htmlFor="sms-user">Username</label>
          <input id="sms-user" value={user} onChange={(e) => setUser(e.target.value)} placeholder="e.g. bot_downtown" />
        </div>
        <button type="submit" className="btn-secondary">
          Show
        </button>
        <button type="button" className="btn-secondary" onClick={() => void load(applied)}>
          Refresh
        </button>
      </form>
      {error && <p role="alert" className="error">{error}</p>}
      {msgs === null ? (
        <Spinner />
      ) : msgs.length === 0 ? (
        <p>No messages yet.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Time (UTC)</th>
              <th scope="col">To user</th>
              <th scope="col">Phone</th>
              <th scope="col">Message</th>
            </tr>
          </thead>
          <tbody>
            {msgs.map((m) => (
              <tr key={m.id}>
                <td className="nowrap">{m.created_at.replace("T", " ").replace("Z", "").slice(0, 19)}</td>
                <td>{m.user}</td>
                <td>{m.phone}</td>
                <td>
                  Your LedgerLab verification code is <strong>{m.code}</strong>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
