export const FLASH_KEY = "ledgerlab.flash";

export class ApiError extends Error {
  status: number;
  code: string;
  data: Record<string, any>;
  constructor(status: number, code: string, message: string, data: Record<string, any> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export const handlers: {
  onSessionEnded?: (code: string, message: string) => void;
  onMaintenance?: () => void;
} = {};

type Opts = { method?: string; body?: unknown; query?: Record<string, string | number | undefined> };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  let url = "/api" + path;
  if (opts.query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(opts.query)) if (v !== undefined && v !== "") qs.set(k, String(v));
    const s = qs.toString();
    if (s) url += "?" + s;
  }
  const res = await fetch(url, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    const err = new ApiError(res.status, data?.code ?? "error", data?.message ?? res.statusText, data ?? {});
    if (err.code === "idle_timeout" || err.code === "bot_detected") handlers.onSessionEnded?.(err.code, err.message);
    if (res.status === 503 && data?.maintenance) handlers.onMaintenance?.();
    throw err;
  }
  return data as T;
}

export type Me = {
  state: string;
  next: "mfa" | "location" | "app";
  mfa_step?: "email" | "sms";
  user: { username: string; full_name: string; role: string };
  organization: { name: string };
  location: { id: number; name: string } | null;
  locations: { id: number; name: string }[];
};

export type PublicConfig = {
  app_name: string;
  captcha_provider: string;
  recaptcha_site_key: string;
  ui_changed: boolean;
  slow_mode: boolean;
  outage: boolean;
};

export type PatientRow = {
  account_no: string;
  first_name: string;
  last_name: string;
  dob: string;
  guarantor: { account_no: string; name: string; is_self: boolean };
  balance: string;
};

export type LedgerRow = {
  id: number;
  date: string;
  type: string;
  payment_type: string;
  note: string;
  apply_to: string;
  amount: string;
  balance: string;
};

export function money(v: string): string {
  const neg = v.startsWith("-");
  const [w, f] = v.replace("-", "").split(".");
  const whole = w.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "-" : ""}$${whole}.${f}`;
}
