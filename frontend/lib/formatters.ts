// Bloomberg-style formatters

export function fmtCurrency(value: number | null | undefined, currency = "USD", compact = false): string {
  if (value == null || isNaN(value)) return "—";
  const opts: Intl.NumberFormatOptions = {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    ...(compact && Math.abs(value) >= 1_000_000
      ? { notation: "compact", compactDisplay: "short" }
      : {}),
  };
  return new Intl.NumberFormat("en-US", opts).format(value);
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value == null || isNaN(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || isNaN(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtShares(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return "—";
  return value.toFixed(4);
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", { dateStyle: "short", timeStyle: "short" });
}

export function colorClass(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return "text-bloomberg-muted";
  return value >= 0 ? "text-bloomberg-green" : "text-bloomberg-red";
}

export function signPrefix(value: number | null | undefined): string {
  if (value == null) return "";
  return value >= 0 ? "▲" : "▼";
}

export const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
