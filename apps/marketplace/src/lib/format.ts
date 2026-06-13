// Display helpers.

export function formatPrice(priceCents: number, currency = "EUR"): string {
  const value = priceCents / 100;
  try {
    return new Intl.NumberFormat("de-DE", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value.toFixed(0)} ${currency}`;
  }
}

export function eurosToCents(euros: number): number {
  return Math.round(euros * 100);
}
