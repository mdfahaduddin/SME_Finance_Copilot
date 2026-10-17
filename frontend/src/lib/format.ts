let defaultCurrency = "USD";

/** The signed-in business's currency, used when money() is called without one. Set by AuthProvider. */
export function setDefaultCurrency(currency: string | undefined): void {
  defaultCurrency = currency || "USD";
}

export function money(value: number, currency = defaultCurrency, compact = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: compact ? 1 : 0,
    notation: compact ? "compact" : "standard",
  }).format(value);
}

export function pct(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}
