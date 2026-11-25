import { useState } from "react";
import { signUp } from "../lib/api.js";
import AuthLayout from "./AuthLayout.jsx";
import { ErrorNote, Field } from "./FormParts.jsx";

const EMPTY_FORM = {
  first_name: "",
  last_name: "",
  email: "",
  phone_number: "",
  date_of_birth: "",
  nationality: "",
  address: "",
  bvn: "",
  password: "",
  confirm_password: "",
};

export default function SignUpPage({ onSignedUp }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [busy, setBusy] = useState(false);

  function updateField(event) {
    setForm({ ...form, [event.target.name]: event.target.value });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setFieldErrors({});

    // Optional fields left empty must not be sent: the API rejects "" as a date.
    const details = {};
    for (const [name, value] of Object.entries(form)) {
      if (value !== "") {
        details[name] = value;
      }
    }

    try {
      await signUp(details);
      onSignedUp();
    } catch (err) {
      setError(err.message);
      setFieldErrors(err.fieldErrors || {});
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Create your account" intro="Add your ID documents after signing in.">
      <ErrorNote message={error} />
      <form onSubmit={handleSubmit}>
        <div className="field-row">
          <Field label="First name" error={fieldErrors.first_name}>
            <input name="first_name" value={form.first_name} onChange={updateField} autoComplete="given-name" required />
          </Field>
          <Field label="Last name" error={fieldErrors.last_name}>
            <input name="last_name" value={form.last_name} onChange={updateField} autoComplete="family-name" required />
          </Field>
        </div>
        <Field label="Email" error={fieldErrors.email}>
          <input type="email" name="email" value={form.email} onChange={updateField} autoComplete="email" required />
        </Field>
        <div className="field-row">
          <Field label="Phone (optional)" error={fieldErrors.phone_number}>
            <input type="tel" name="phone_number" value={form.phone_number} onChange={updateField} autoComplete="tel" maxLength={15} />
          </Field>
          <Field label="Date of birth (optional)" error={fieldErrors.date_of_birth}>
            <input type="date" name="date_of_birth" value={form.date_of_birth} onChange={updateField} autoComplete="bday" />
          </Field>
        </div>
        <Field label="Nationality (optional)" error={fieldErrors.nationality}>
          <input name="nationality" value={form.nationality} onChange={updateField} />
        </Field>
        <Field label="Address (optional)" error={fieldErrors.address}>
          <input name="address" value={form.address} onChange={updateField} autoComplete="street-address" />
        </Field>
        <Field label="BVN (optional)" error={fieldErrors.bvn} hint="11 digits. Only the last 4 are ever shown.">
          <input name="bvn" value={form.bvn} onChange={updateField} inputMode="numeric" maxLength={11} autoComplete="off" />
        </Field>
        <Field label="Password" error={fieldErrors.password}>
          <input type="password" name="password" value={form.password} onChange={updateField} autoComplete="new-password" required />
        </Field>
        <Field label="Confirm password" error={fieldErrors.confirm_password}>
          <input type="password" name="confirm_password" value={form.confirm_password} onChange={updateField} autoComplete="new-password" required />
        </Field>
        <button className="button button-primary" disabled={busy}>
          {busy ? "Creating account..." : "Create account"}
        </button>
      </form>
      <div className="auth-links">
        <a href="#/signin">Already have an account? Sign in</a>
      </div>
    </AuthLayout>
  );
}
