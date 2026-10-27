import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Spinner, useUi } from "../ui";

type Row = { id: number; time: string; event: string; user: string; location: string; ip: string; result: string; detail: string };
type Resp = { total: number; events: string[]; rows: Row[] };

const PAGE = 50;

export default function DevAudit() {
  const ui = useUi();
  const [event, setEvent] = useState("");
  const [user, setUser] = useState("");
  const [result, setResult] = useState("");
  const [location, setLocation] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Resp | null>(null);
  const [events, setEvents] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(
    async (off: number, f = { event, user, result, location, q }) => {
      setLoading(true);
      setError("");
      try {
        const r = await api<Resp>("/dev/audit", { query: { ...f, limit: PAGE, offset: off } });
        setData(r);
        setEvents(r.events);
        setOffset(off);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not load the audit log.");
      } finally {
        setLoading(false);
      }
    },
    // filters are applied on submit, so they are read at call time
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    void load(0, { event: "", user: "", result: "", location: "", q: "" });
  }, [load]);

  function apply(e: FormEvent) {
    e.preventDefault();
    void load(0, { event, user, result, location, q });
  }

  function clear() {
    setEvent("");
    setUser("");
    setResult("");
    setLocation("");
    setQ("");
    void load(0, { event: "", user: "", result: "", location: "", q: "" });
  }

  const f = { event, user, result, location, q };
  return (
    <section>
      <h1>Audit Log</h1>
      <form onSubmit={apply} className="filters">
        <div className={ui.cls("field")}>
          <label htmlFor="f-event">Event</label>
          <select id="f-event" value={event} onChange={(e) => setEvent(e.target.value)}>
            <option value="">All events</option>
            {events.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </div>
        <div className={ui.cls("field")}>
          <label htmlFor="f-user">User</label>
          <input id="f-user" value={user} onChange={(e) => setUser(e.target.value)} />
        </div>
        <div className={ui.cls("field")}>
          <label htmlFor="f-result">Result</label>
          <select id="f-result" value={result} onChange={(e) => setResult(e.target.value)}>
            <option value="">Any</option>
            <option value="success">success</option>
            <option value="failure">failure</option>
            <option value="info">info</option>
          </select>
        </div>
        <div className={ui.cls("field")}>
          <label htmlFor="f-location">Location</label>
          <select id="f-location" value={location} onChange={(e) => setLocation(e.target.value)}>
            <option value="">Any</option>
            <option value="Downtown">Downtown</option>
            <option value="Lakeside">Lakeside</option>
          </select>
        </div>
        <div className={ui.cls("field")}>
          <label htmlFor="f-q">Text / IP</label>
          <input id="f-q" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="filter-buttons">
          <button type="submit" className={ui.cls("primary")}>
            Apply filters
          </button>
          <button type="button" className={ui.cls("secondary")} onClick={clear}>
            Clear
          </button>
          <button type="button" className={ui.cls("secondary")} onClick={() => void load(offset, f)}>
            Refresh
          </button>
        </div>
      </form>
      {error && <p role="alert" className="error">{error}</p>}
      {loading && <Spinner />}
      {!loading && data && (
        <>
          <p className="muted">
            {data.total} entr{data.total === 1 ? "y" : "ies"}
            {data.total > 0 && ` · showing ${offset + 1}–${Math.min(offset + PAGE, data.total)}`}
          </p>
          <table className={ui.cls("table")}>
            <thead>
              <tr>
                <th scope="col">Time (UTC)</th>
                <th scope="col">Event</th>
                <th scope="col">User</th>
                <th scope="col">Location</th>
                <th scope="col">IP</th>
                <th scope="col">Result</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap">{r.time.replace("T", " ").replace("Z", "").slice(0, 19)}</td>
                  <td>{r.event}</td>
                  <td>{r.user}</td>
                  <td>{r.location}</td>
                  <td>{r.ip}</td>
                  <td className={`res-${r.result}`}>{r.result}</td>
                  <td>{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button type="button" className={ui.cls("secondary")} disabled={offset === 0} onClick={() => void load(Math.max(0, offset - PAGE), f)}>
              Previous
            </button>{" "}
            <button type="button" className={ui.cls("secondary")} disabled={offset + PAGE >= data.total} onClick={() => void load(offset + PAGE, f)}>
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
