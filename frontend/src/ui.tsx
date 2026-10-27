import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, PublicConfig } from "./api";

// ---------------------------------------------------------------- "UI changed" chaos mode
// Normal text vs. text in UI-changed mode. Ids and class names change too.
const TEXT = {
  organization: ["Organization", "Practice group"],
  username: ["Username", "User ID"],
  continue: ["Continue", "Next"],
  password: ["Password", "Passcode"],
  logIn: ["Log In", "Sign In"],
  searchPatients: ["Search patients", "Find a patient"],
  searchBtn: ["Search", "Find"],
  enterPayment: ["Enter Payment", "Add Payment"],
  paymentType: ["Payment type", "Method of payment"],
  amount: ["Amount", "Payment amount"],
  paymentDate: ["Payment date", "Date received"],
  applyTo: ["Apply to", "Allocate to"],
  note: ["Note", "Memo"],
  save: ["Save", "Post payment"],
  cancel: ["Cancel", "Close"],
  ledgerSearch: ["Search notes", "Filter memos"],
  filterBtn: ["Search", "Apply"],
  colDate: ["Date", "Posted"],
  colType: ["Type", "Kind"],
  colPayType: ["Payment type", "Method"],
  colNote: ["Description / Note", "Details"],
  colAmount: ["Amount", "Amt"],
  colBalance: ["Balance", "Running total"],
  logOut: ["Log out", "Sign out"],
  todaysVisit: ["Today's visit", "Current visit"],
  accountBalance: ["Account balance", "Outstanding balance"],
} as const;

export type TextKey = keyof typeof TEXT;

const CLASSES = {
  primary: ["btn-primary", "cta-main"],
  secondary: ["btn-secondary", "cta-alt"],
  modal: ["modal", "dialog-box"],
  field: ["field", "form-row"],
  table: ["data-table", "grid-view"],
  toast: ["toast", "notice-pop"],
} as const;

export type ClassKey = keyof typeof CLASSES;

function shortHash(s: string): string {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h.toString(36);
}

export type UiHelpers = {
  changed: boolean;
  t: (k: TextKey) => string;
  id: (k: string) => string;
  cls: (k: ClassKey) => string;
};

// ---------------------------------------------------------------- toasts
type Toast = { id: number; text: string; kind: "success" | "error" };

type Ctx = {
  config: PublicConfig | null;
  refreshConfig: () => Promise<void>;
  ui: UiHelpers;
  toast: (text: string, kind?: Toast["kind"]) => void;
  maintenance: boolean;
  setMaintenance: (v: boolean) => void;
};

const AppContext = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppContext);
export const useUi = () => useContext(AppContext).ui;

export function AppProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [maintenance, setMaintenance] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);

  const refreshConfig = useCallback(async () => {
    try {
      const c = await api<PublicConfig>("/public-config");
      setConfig(c);
    } catch {
      /* keep the previous config */
    }
  }, []);

  useEffect(() => {
    void refreshConfig();
  }, [refreshConfig]);

  const toast = useCallback((text: string, kind: Toast["kind"] = "success") => {
    const id = ++seq.current;
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);

  const changed = !!config?.ui_changed;
  const ui = useMemo<UiHelpers>(
    () => ({
      changed,
      t: (k) => TEXT[k][changed ? 1 : 0],
      id: (k) => (changed ? `f_${shortHash(k)}` : k),
      cls: (k) => CLASSES[k][changed ? 1 : 0],
    }),
    [changed],
  );

  const value = useMemo(
    () => ({ config, refreshConfig, ui, toast, maintenance, setMaintenance }),
    [config, refreshConfig, ui, toast, maintenance],
  );

  return (
    <AppContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`${ui.cls("toast")} ${t.kind === "error" ? "toast-error" : "toast-success"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </AppContext.Provider>
  );
}

// ---------------------------------------------------------------- spinner
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="spinner-wrap" role="status" aria-live="polite" aria-busy="true">
      <span className="spinner" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </div>
  );
}
