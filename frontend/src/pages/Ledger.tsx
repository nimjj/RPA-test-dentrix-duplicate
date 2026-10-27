import { FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, LedgerRow, money, PatientRow } from "../api";
import { Spinner, useApp, useUi } from "../ui";

type PaymentType = { id: number; label: string };

function todayLocal(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export default function Ledger() {
  const { account = "" } = useParams();
  const ui = useUi();
  const { toast } = useApp();
  const [patient, setPatient] = useState<PatientRow | null>(null);
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [filter, setFilter] = useState("");
  const [applied, setApplied] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState(false);

  const load = useCallback(
    async (q: string) => {
      setLoading(true);
      setError("");
      try {
        const r = await api<{ patient: PatientRow; entries: LedgerRow[] }>(`/patients/${encodeURIComponent(account)}/ledger`, {
          query: { q },
        });
        setPatient(r.patient);
        setRows(r.entries);
        setApplied(q);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Something went wrong.");
      } finally {
        setLoading(false);
      }
    },
    [account],
  );

  useEffect(() => {
    void load("");
  }, [load]);

  function onFilter(e: FormEvent) {
    e.preventDefault();
    void load(filter.trim());
  }

  if (error && !patient) {
    return (
      <section>
        <p role="alert" className="error">
          {error}
        </p>
        <Link to="/patients">Back to patient search</Link>
      </section>
    );
  }

  return (
    <section>
      <p>
        <Link to="/patients">← Patients</Link>
      </p>
      {patient && (
        <div className="patient-head">
          <div>
            <h1>
              {patient.last_name}, {patient.first_name}
            </h1>
            <dl className="facts">
              <div>
                <dt>Account #</dt>
                <dd>{patient.account_no}</dd>
              </div>
              <div>
                <dt>Date of birth</dt>
                <dd>{patient.dob}</dd>
              </div>
              <div>
                <dt>Guarantor</dt>
                <dd>{patient.guarantor.is_self ? "Self" : `${patient.guarantor.name} (${patient.guarantor.account_no})`}</dd>
              </div>
              <div>
                <dt>Current balance</dt>
                <dd className="balance">{money(patient.balance)}</dd>
              </div>
            </dl>
          </div>
          <button type="button" className={ui.cls("primary")} onClick={() => setModal(true)}>
            {ui.t("enterPayment")}
          </button>
        </div>
      )}

      <form onSubmit={onFilter} className="inline-form" role="search">
        <div className={ui.cls("field")}>
          <label htmlFor={ui.id("ledger-search")}>{ui.t("ledgerSearch")}</label>
          <input id={ui.id("ledger-search")} value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <button type="submit" className={ui.cls("secondary")} disabled={loading}>
          {ui.t("filterBtn")}
        </button>
      </form>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {loading ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <p>{applied ? `No transactions match “${applied}”.` : "No transactions yet."}</p>
      ) : (
        <table className={ui.cls("table")}>
          <caption className="sr-only">Patient ledger</caption>
          <thead>
            <tr>
              <th scope="col">{ui.t("colDate")}</th>
              <th scope="col">{ui.t("colType")}</th>
              <th scope="col">{ui.t("colPayType")}</th>
              <th scope="col">{ui.t("colNote")}</th>
              <th scope="col" className="num">
                {ui.t("colAmount")}
              </th>
              <th scope="col" className="num">
                {ui.t("colBalance")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.date}</td>
                <td className="cap">{r.type}</td>
                <td>{r.payment_type}</td>
                <td>{r.note}</td>
                <td className="num">{money(r.amount)}</td>
                <td className="num">{money(r.balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {modal && (
        <PaymentModal
          account={account}
          onClose={() => setModal(false)}
          onSaved={() => {
            setModal(false);
            toast("Payment saved.");
            setFilter("");
            void load("");
          }}
        />
      )}
    </section>
  );
}

function PaymentModal({ account, onClose, onSaved }: { account: string; onClose: () => void; onSaved: () => void }) {
  const ui = useUi();
  const [types, setTypes] = useState<PaymentType[] | null>(null);
  const [typeId, setTypeId] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(todayLocal());
  const [applyTo, setApplyTo] = useState("todays_visit");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ payment_types: PaymentType[] }>("/locations/current/payment-types")
      .then((r) => setTypes(r.payment_types))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load payment types."));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !saving && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, saving]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await api(`/patients/${encodeURIComponent(account)}/payments`, {
        body: { payment_type_id: Number(typeId), amount: amount.trim(), payment_date: date, apply_to: applyTo, note },
      });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setSaving(false);
    }
  }

  const formId = ui.id("payment-form");
  const saveBtn = (
    <button type="submit" form={formId} className={ui.cls("primary")} disabled={saving || !typeId || !amount.trim() || !date}>
      {saving ? "Saving…" : ui.t("save")}
    </button>
  );
  const cancelBtn = (
    <button type="button" className={ui.cls("secondary")} onClick={onClose} disabled={saving}>
      {ui.t("cancel")}
    </button>
  );

  return (
    <div className="backdrop">
      <div className={ui.cls("modal")} role="dialog" aria-modal="true" aria-labelledby={ui.id("payment-title")}>
        <div className="modal-head">
          <h2 id={ui.id("payment-title")}>{ui.t("enterPayment")}</h2>
          {/* UI-changed mode moves the primary action to the top right of the dialog */}
          {ui.changed && saveBtn}
        </div>
        {types === null && !error ? (
          <Spinner />
        ) : (
          <form id={formId} onSubmit={submit}>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("payment-type")}>{ui.t("paymentType")}</label>
              <select id={ui.id("payment-type")} value={typeId} onChange={(e) => setTypeId(e.target.value)}>
                <option value="">Select…</option>
                {(types ?? []).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("amount")}>{ui.t("amount")}</label>
              <input
                id={ui.id("amount")}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                inputMode="decimal"
                placeholder="0.00"
                autoComplete="off"
              />
            </div>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("payment-date")}>{ui.t("paymentDate")}</label>
              <input id={ui.id("payment-date")} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </div>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("apply-to")}>{ui.t("applyTo")}</label>
              <select id={ui.id("apply-to")} value={applyTo} onChange={(e) => setApplyTo(e.target.value)}>
                <option value="todays_visit">{ui.t("todaysVisit")}</option>
                <option value="account_balance">{ui.t("accountBalance")}</option>
              </select>
            </div>
            <div className={ui.cls("field")}>
              <label htmlFor={ui.id("note")}>{ui.t("note")}</label>
              <textarea
                id={ui.id("note")}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={255}
                rows={3}
              />
              <small className="muted">{note.length}/255</small>
            </div>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
          </form>
        )}
        <div className={ui.changed ? "modal-foot modal-foot-left" : "modal-foot"}>
          {ui.changed ? (
            cancelBtn
          ) : (
            <>
              {cancelBtn}
              {saveBtn}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
