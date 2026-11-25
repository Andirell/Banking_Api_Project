const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const SLOW_REQUEST_MS = 4000;

// Tokens stay in this tab's sessionStorage, and go away when the tab closes.
// Keeping the access token there means a reload doesn't need a refresh. Refresh
// tokens work once, so a reload during a refresh would otherwise sign the user out.
let accessToken = readStoredToken(ACCESS_TOKEN_KEY);
let refreshInProgress = null;
let onSessionExpired = () => {};
let onSlowChange = () => {};
let slowRequests = 0;

export class ApiError extends Error {
  constructor(status, message, fieldErrors = {}) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

export function setApiListeners(listeners) {
  onSessionExpired = listeners.onSessionExpired;
  onSlowChange = listeners.onSlowChange;
}

function readStoredToken(key) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function saveTokens(newAccessToken, newRefreshToken) {
  accessToken = newAccessToken;
  try {
    sessionStorage.setItem(ACCESS_TOKEN_KEY, newAccessToken);
    sessionStorage.setItem(REFRESH_TOKEN_KEY, newRefreshToken);
  } catch {
    // Storage can be blocked. The user just has to sign in again after a reload.
  }
}

function clearTokens() {
  accessToken = null;
  try {
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  } catch {
    // Nothing was stored, so there is nothing to remove.
  }
}

export function hasSession() {
  return Boolean(accessToken || readStoredToken(REFRESH_TOKEN_KEY));
}

function firstMessage(value) {
  if (Array.isArray(value)) {
    return String(value[0]);
  }
  return String(value);
}

// The API has a few error shapes: {error}, {detail}, {errors: {...}} and {field: [...]}.
function buildApiError(status, data, retryAfter) {
  if (status === 429) {
    if (retryAfter) {
      return new ApiError(status, `Too many attempts. Try again in ${retryAfter} seconds.`);
    }
    return new ApiError(status, data?.error || "Too many attempts. Try again later.");
  }

  if (data?.error) {
    return new ApiError(status, data.error);
  }
  if (data?.detail) {
    return new ApiError(status, firstMessage(data.detail));
  }

  const rawFields = data?.errors || data;
  if (rawFields && typeof rawFields === "object") {
    const fieldErrors = {};
    for (const [field, value] of Object.entries(rawFields)) {
      fieldErrors[field] = firstMessage(value);
    }
    const message = fieldErrors.non_field_errors || "Please check the highlighted fields.";
    return new ApiError(status, message, fieldErrors);
  }

  return new ApiError(status, "The server had a problem. Try again in a moment.");
}

async function sendRequest(path, options, useToken) {
  const headers = {};
  let body;

  if (options.formData) {
    body = options.formData; // The browser sets the multipart content type itself.
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (useToken && accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  // A free server can take a while to wake up, so tell the user after a few seconds.
  let reportedSlow = false;
  const slowTimer = setTimeout(() => {
    reportedSlow = true;
    slowRequests += 1;
    onSlowChange(true);
  }, SLOW_REQUEST_MS);

  try {
    return await fetch(path, { method: options.method || "GET", headers, body });
  } catch {
    throw new ApiError(0, "We couldn't reach the server. Check your connection and try again.");
  } finally {
    clearTimeout(slowTimer);
    if (reportedSlow) {
      slowRequests -= 1;
      if (slowRequests === 0) {
        onSlowChange(false);
      }
    }
  }
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function requestNewTokens() {
  const refreshToken = readStoredToken(REFRESH_TOKEN_KEY);
  if (!refreshToken) {
    return false;
  }

  const response = await sendRequest(
    "/users/token/refresh/",
    { method: "POST", body: { refresh: refreshToken } },
    false
  );
  if (!response.ok) {
    return false;
  }

  const data = await readJson(response);
  saveTokens(data.access, data.refresh);
  return true;
}

// Each refresh token works only once, so requests that fail together must share
// one refresh. A second refresh would be rejected and sign the user out.
function refreshTokens() {
  if (!refreshInProgress) {
    refreshInProgress = requestNewTokens().finally(() => {
      refreshInProgress = null;
    });
  }
  return refreshInProgress;
}

async function request(path, options = {}) {
  const needsAuth = options.auth !== false;
  let response = await sendRequest(path, options, needsAuth);

  // A 401 means the server rejected the token and did nothing, so this retry
  // can't move money twice. Other failures are never retried automatically.
  if (needsAuth && response.status === 401) {
    const refreshed = await refreshTokens();
    if (!refreshed) {
      clearTokens();
      onSessionExpired();
      throw new ApiError(401, "Your session has ended. Please sign in again.");
    }
    response = await sendRequest(path, options, true);
  }

  const data = await readJson(response);
  if (!response.ok) {
    throw buildApiError(response.status, data, response.headers.get("Retry-After"));
  }
  return data;
}

function post(path, body, auth = true) {
  return request(path, { method: "POST", body, auth });
}

export function signUp(details) {
  return post("/users/signup/", details, false);
}

export function signIn(email, password) {
  return post("/users/signin/", { email, password }, false);
}

export async function verifySignInCode(email, otp) {
  const data = await post("/users/verify-signin-otp/", { email, otp }, false);
  saveTokens(data.access_token, data.refresh_token);
}

export async function signOut() {
  const refreshToken = readStoredToken(REFRESH_TOKEN_KEY);
  try {
    if (refreshToken) {
      await post("/users/logout/", { refresh_token: refreshToken });
    }
  } finally {
    // Always clear this browser, even if the server could not be reached.
    clearTokens();
  }
}

export function requestPasswordReset(email) {
  return post("/users/request-password-reset/", { email }, false);
}

export function verifyPasswordResetCode(email, otp) {
  return post("/users/verify-password-reset-otp/", { email, otp }, false);
}

export function resetPassword(email, newPassword, confirmPassword) {
  return post(
    "/users/reset-password/",
    { email, new_password: newPassword, confirm_password: confirmPassword },
    false
  );
}

export function getProfile() {
  return request("/users/me/");
}

export function getWallet() {
  return request("/wallets/details/");
}

export function getTransactions() {
  return request("/transactions/");
}

export function sendMoney(receiverEmail, amount, description) {
  return post("/transactions/send/", { receiver_email: receiverEmail, amount, description });
}

export function getLoans() {
  return request("/loans/");
}

export function applyForLoan(amount, durationMonths, reason) {
  return post("/loans/apply/", { amount, duration_months: durationMonths, reason });
}

export function getUnpaidInstallments() {
  return request("/loans/emis/");
}

export function payInstallment(installmentId) {
  return post(`/loans/emis/${installmentId}/pay/`);
}

export function submitKycDocuments(identityDocument, proofOfAddress) {
  const formData = new FormData();
  formData.append("identity_document", identityDocument);
  formData.append("proof_of_address", proofOfAddress);
  return request("/users/kyc/submit/", { method: "POST", formData });
}
