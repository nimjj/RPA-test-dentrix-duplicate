import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, money, PatientRow } from "../api";
import { Spinner, useUi } from "../ui";

export default function Patients() {
  const ui = useUi();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PatientRow[] | null>(null);
  const [searched, setSearched] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function search(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const r = await api<{ results: PatientRow[] }>("/patients", { query: { q: q.trim() } });
      setResults(r.results);
      setSearched(q.trim());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section>
      <h1>Patients</h1>
      <form onSubmit={search} className="inline-form" role="search">
        <div className={ui.cls("field")}>
          <label htmlFor={ui.id("patient-search")}>{ui.t("searchPatients")}</label>
          <input
            id={ui.id("patient-search")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Account number or name"
            autoFocus
          />
        </div>
        <button type="submit" className={ui.cls("primary")} disabled={loading}>
          {ui.t("searchBtn")}
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading && <Spinner />}
      {!loading && results === null && <p className="muted">Search by account number (for example DT-100234) or by name.</p>}
      {!loading && results !== null && results.length === 0 && (
        <p>No patients found{searched ? ` for “${searched}”` : ""}.</p>
      )}
      {!loading && results !== null && results.length > 0 && (
        <table className={ui.cls("table")}>
          <caption className="sr-only">Patient search results</caption>
          <thead>
            <tr>
              <th scope="col">Account #</th>
              <th scope="col">Patient</th>
              <th scope="col">Date of birth</th>
              <th scope="col">Guarantor</th>
              <th scope="col" className="num">
                Balance
              </th>
            </tr>
          </thead>
          <tbody>
            {results.map((p) => (
              <tr key={p.account_no}>
                <td>
                  <Link to={`/patients/${p.account_no}/ledger`}>{p.account_no}</Link>
                </td>
                <td>
                  {p.last_name}, {p.first_name}
                </td>
                <td>{p.dob}</td>
                <td>{p.guarantor.is_self ? "Self" : `${p.guarantor.name} (${p.guarantor.account_no})`}</td>
                <td className="num">{money(p.balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
