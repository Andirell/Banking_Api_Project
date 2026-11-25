import { useState } from "react";
import { requestPasswordReset, resetPassword, verifyPasswordResetCode } from "../lib/api.js";
import AuthLayout from "./AuthLayout.jsx";
import { ErrorNote, Field, SuccessNote } from "./FormParts.jsx";

export default function ForgotPasswordPage({ onPasswordReset }) {
  const [step, setStep] = useState("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleEmailSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await requestPasswordReset(email);
      setInfo(result.message);
      setStep("code");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCodeSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await verifyPasswordResetCode(email, code);
      setInfo("");
      setStep("password");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handlePasswordSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await resetPassword(email, newPassword, confirmPassword);
      onPasswordReset();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Reset your password">
      <SuccessNote message={info} />
      <ErrorNote message={error} />

      {step === "email" && (
        <form onSubmit={handleEmailSubmit}>
          <Field label="Email">
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required autoFocus />
          </Field>
          <button className="button button-primary" disabled={busy}>
            {busy ? "Sending..." : "Send reset code"}
          </button>
        </form>
      )}

      {step === "code" && (
        <form onSubmit={handleCodeSubmit}>
          <Field label="Reset code">
            <input
              className="code-input"
              value={code}
              onChange={(event) => setCode(event.target.value.trim())}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              required
              autoFocus
            />
          </Field>
          <button className="button button-primary" disabled={busy}>
            {busy ? "Checking..." : "Verify code"}
          </button>
        </form>
      )}

      {step === "password" && (
        <form onSubmit={handlePasswordSubmit}>
          <Field label="New password">
            <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required autoFocus />
          </Field>
          <Field label="Confirm new password">
            <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} autoComplete="new-password" required />
          </Field>
          <button className="button button-primary" disabled={busy}>
            {busy ? "Saving..." : "Set new password"}
          </button>
        </form>
      )}

      <div className="auth-links">
        <a href="#/signin">Back to sign in</a>
      </div>
    </AuthLayout>
  );
}
