import { useState } from "react";
import { signIn, verifySignInCode } from "../lib/api.js";
import AuthLayout from "./AuthLayout.jsx";
import { ErrorNote, Field, SuccessNote } from "./FormParts.jsx";

export default function SignInPage({ notice, onSignedIn }) {
  const [step, setStep] = useState("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState(notice || "");
  const [failedPassword, setFailedPassword] = useState(false);
  const [busy, setBusy] = useState(false);

  async function requestCode() {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const result = await signIn(email, password);
      setEmail(result.email);
      setCode("");
      setStep("code");
      setInfo(`We sent a 6-digit code to ${result.email}.`);
    } catch (err) {
      setError(err.message);
      setFailedPassword(err.status === 401);
    } finally {
      setBusy(false);
    }
  }

  async function handlePasswordSubmit(event) {
    event.preventDefault();
    await requestCode();
  }

  async function handleCodeSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await verifySignInCode(email, code);
      setPassword("");
      await onSignedIn();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  function startAgain() {
    setStep("password");
    setPassword("");
    setCode("");
    setError("");
    setInfo("");
  }

  if (step === "code") {
    return (
      <AuthLayout title="Enter your code" intro="The code expires after 5 minutes.">
        <SuccessNote message={info} />
        <ErrorNote message={error} />
        <form onSubmit={handleCodeSubmit}>
          <Field label="Sign-in code">
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
            {busy ? "Checking..." : "Verify and sign in"}
          </button>
        </form>
        <div className="auth-links">
          <button type="button" className="link-button" onClick={requestCode} disabled={busy}>
            Send a new code
          </button>
          <button type="button" className="link-button" onClick={startAgain} disabled={busy}>
            Use a different account
          </button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Sign in" intro="Your password, then a code sent to your email.">
      <SuccessNote message={info} />
      <ErrorNote message={error} />
      {failedPassword && (
        <p className="field-hint">After 5 wrong passwords, an account locks for 15 minutes.</p>
      )}
      <form onSubmit={handlePasswordSubmit}>
        <Field label="Email">
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="username"
            required
            autoFocus
          />
        </Field>
        <Field label="Password">
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        <button className="button button-primary" disabled={busy}>
          {busy ? "Checking..." : "Continue"}
        </button>
      </form>
      <div className="auth-links">
        <a href="#/forgot-password">Forgot password?</a>
        <a href="#/signup">Create an account</a>
      </div>
    </AuthLayout>
  );
}
