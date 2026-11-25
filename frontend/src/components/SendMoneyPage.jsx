import { useEffect, useState } from "react";
import { getWallet, sendMoney } from "../lib/api.js";
import { formatMoney, isValidAmount } from "../lib/format.js";
import { ErrorNote, Field, Loading } from "./FormParts.jsx";

// The API has no retry protection on transfers, so when we can't tell whether one
// went through, the user must check first instead of sending it a second time.
function outcomeIsUnknown(err) {
  return err.status === 0 || err.status >= 500;
}

export default function SendMoneyPage() {
  const [wallet, setWallet] = useState(null);
  const [step, setStep] = useState("form");
  const [receiverEmail, setReceiverEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState("");
  const [needsKyc, setNeedsKyc] = useState(false);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stillOnPage = true;
    getWallet()
      .then((data) => {
        if (stillOnPage) {
          setWallet(data);
        }
      })
      .catch((err) => {
        if (stillOnPage) {
          setError(err.message);
        }
      });
    return () => {
      stillOnPage = false;
    };
  }, []);

  function handleReview(event) {
    event.preventDefault();
    setError("");
    setNeedsKyc(false);
    setFieldErrors({});
    if (!isValidAmount(amount)) {
      setFieldErrors({ amount: "Enter an amount above zero, with at most 2 decimal places." });
      return;
    }
    setStep("review");
  }

  async function handleConfirm() {
    setBusy(true);
    setError("");
    try {
      const response = await sendMoney(receiverEmail, amount, description);
      setResult(response);
      setStep("done");
    } catch (err) {
      setStep("form");
      setFieldErrors(err.fieldErrors || {});
      setNeedsKyc(err.status === 403);
      if (outcomeIsUnknown(err)) {
        setError("We couldn't confirm this transfer. Check your transactions before trying again.");
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  function startNewTransfer() {
    setReceiverEmail("");
    setAmount("");
    setDescription("");
    setResult(null);
    setStep("form");
  }

  if (!wallet) {
    return error ? <ErrorNote message={error} /> : <Loading />;
  }

  if (step === "done") {
    return (
      <section className="panel narrow">
        <p className="eyebrow">Transfer complete</p>
        <h1>{formatMoney(result.transaction.amount, wallet.currency)} sent</h1>
        <p className="muted">To {result.transaction.receiver}</p>
        <dl className="details">
          <div><dt>New balance</dt><dd>{formatMoney(result.balance, wallet.currency)}</dd></div>
          <div><dt>Reference</dt><dd className="reference">{result.transaction.reference}</dd></div>
        </dl>
        <div className="button-row">
          <a className="button button-primary" href="#/dashboard">Back to overview</a>
          <button type="button" className="button" onClick={startNewTransfer}>Send another</button>
        </div>
      </section>
    );
  }

  if (step === "review") {
    return (
      <section className="panel narrow">
        <p className="eyebrow">Check the details</p>
        <h1>Send {formatMoney(amount, wallet.currency)}?</h1>
        <dl className="details">
          <div><dt>To</dt><dd>{receiverEmail}</dd></div>
          {description && <div><dt>Note</dt><dd>{description}</dd></div>}
        </dl>
        <div className="button-row">
          <button type="button" className="button button-primary" onClick={handleConfirm} disabled={busy}>
            {busy ? "Sending..." : "Confirm and send"}
          </button>
          <button type="button" className="button" onClick={() => setStep("form")} disabled={busy}>Edit</button>
        </div>
      </section>
    );
  }

  return (
    <section className="panel narrow">
      <h1>Send money</h1>
      <p className="muted">Available: {formatMoney(wallet.balance, wallet.currency)}</p>
      <ErrorNote message={error} />
      {needsKyc && <p><a href="#/kyc">Go to identity verification</a></p>}
      <form onSubmit={handleReview}>
        <Field label="Receiver's email" error={fieldErrors.receiver_email}>
          <input type="email" value={receiverEmail} onChange={(event) => setReceiverEmail(event.target.value)} required autoFocus />
        </Field>
        <Field label="Amount" error={fieldErrors.amount}>
          <input value={amount} onChange={(event) => setAmount(event.target.value.trim())} inputMode="decimal" placeholder="0.00" required />
        </Field>
        <Field label="Note (optional)" error={fieldErrors.description}>
          <input value={description} onChange={(event) => setDescription(event.target.value)} />
        </Field>
        <button className="button button-primary">Review transfer</button>
      </form>
    </section>
  );
}
