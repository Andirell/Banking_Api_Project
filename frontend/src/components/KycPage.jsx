import { useState } from "react";
import { submitKycDocuments } from "../lib/api.js";
import { ErrorNote, Field, SuccessNote } from "./FormParts.jsx";
import { getKycSummary, KycBadge } from "./KycStatus.jsx";

const MAX_FILE_SIZE = 5 * 1024 * 1024;

function getFileProblem(file) {
  if (file && file.size > MAX_FILE_SIZE) {
    return "This file is larger than 5MB.";
  }
  return "";
}

export default function KycPage({ user, onSubmitted }) {
  const [identityDocument, setIdentityDocument] = useState(null);
  const [proofOfAddress, setProofOfAddress] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  const summary = getKycSummary(user);
  const identityProblem = getFileProblem(identityDocument);
  const addressProblem = getFileProblem(proofOfAddress);

  async function handleSubmit(event) {
    event.preventDefault();
    if (identityProblem || addressProblem) {
      return;
    }

    setBusy(true);
    setError("");
    setSuccess("");
    setFieldErrors({});
    try {
      await submitKycDocuments(identityDocument, proofOfAddress);
      await onSubmitted();
      setSuccess("Documents received. Staff will review them.");
      event.target.reset();
      setIdentityDocument(null);
      setProofOfAddress(null);
    } catch (err) {
      setError(err.message);
      setFieldErrors(err.fieldErrors || {});
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel narrow">
      <h1>Identity verification</h1>
      <div className="status-line"><KycBadge user={user} /></div>
      <p className="muted">{summary.text}</p>
      <SuccessNote message={success} />
      <ErrorNote message={error} />

      {user.kyc_status === "verified" ? (
        <p className="muted">No further action is needed.</p>
      ) : (
        <form onSubmit={handleSubmit}>
          {user.kyc_documents_submitted && (
            <p className="field-hint">Uploading again replaces your earlier documents and restarts the review.</p>
          )}
          <Field label="Identity document" error={identityProblem || fieldErrors.identity_document} hint="An image, up to 5MB">
            <input type="file" accept="image/*" onChange={(event) => setIdentityDocument(event.target.files[0] || null)} required />
          </Field>
          <Field label="Proof of address" error={addressProblem || fieldErrors.proof_of_address} hint="An image, up to 5MB">
            <input type="file" accept="image/*" onChange={(event) => setProofOfAddress(event.target.files[0] || null)} required />
          </Field>
          <button className="button button-primary" disabled={busy}>
            {busy ? "Uploading..." : "Submit documents"}
          </button>
          <p className="field-hint">Your documents are private: only you and staff can open them.</p>
        </form>
      )}
    </section>
  );
}
