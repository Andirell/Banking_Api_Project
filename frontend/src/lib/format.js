// Amounts stay as strings from the API. Numbers are only used to display them,
// never for calculations, so no money is lost to rounding.
export function formatMoney(amount, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(amount));
}

export function formatDate(dateText) {
  return new Date(dateText).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function isValidAmount(text) {
  return /^\d+(\.\d{1,2})?$/.test(text) && Number(text) > 0;
}
