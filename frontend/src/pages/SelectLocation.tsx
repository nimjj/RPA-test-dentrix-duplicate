import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useMe } from "../components/Layout";
import { useUi } from "../ui";

export default function SelectLocation() {
  const { me, reload } = useMe();
  const ui = useUi();
  const navigate = useNavigate();
  const [choice, setChoice] = useState<number | "">(me.location?.id ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (choice === "") return;
    setBusy(true);
    setError("");
    try {
      await api("/auth/location", { body: { location_id: choice } });
      await reload();
      navigate("/patients", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-page">
      <div className="card">
        <h1>Choose a location</h1>
        <p className="muted">Signed in as {me.user.full_name}</p>
        <form onSubmit={submit}>
          <fieldset>
            <legend>Location</legend>
            {me.locations.map((l) => (
              <label key={l.id} className="radio">
                <input type="radio" name="location" value={l.id} checked={choice === l.id} onChange={() => setChoice(l.id)} />
                {l.name}
              </label>
            ))}
          </fieldset>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <button type="submit" className={ui.cls("primary")} disabled={busy || choice === ""}>
            Continue
          </button>
        </form>
      </div>
    </div>
  );
}
