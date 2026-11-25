import { useEffect, useState } from "react";
import { applyForLoan, getLoans, getUnpaidInstallments, getWallet, payInstallment } from "../lib/api.js";
import { formatDate, formatMoney, isValidAmount } from "../lib/format.js";
import { ErrorNote, Field, Loading, SuccessNote } from "./FormParts.jsx";

const STATUS_BADGES = { pending: "waiting", approved: "good", rejected: "bad" };

function ApplyForm({ onApplied }) {
  const [amount, setAmount] = useState("");
  const [months, setMonths] = useState("");
  const [reason, setReason] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setFieldErrors({});
    if (!isValidAmount(amount)) {
      setFieldErrors({ amount: "Enter an amount above zero, with at most 2 decimal places." });
      return;
    }

    setBusy(true);
    try {
      await applyForLoan(amount, Number(months), reason);
      setAmount("");
      setMonths("");
      setReason("");
      await onApplied();
    } catch (err) {
      setError(err.message);
      setFieldErrors(err.fieldErrors || {});
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h2>Apply for a loan</h2>
      <ErrorNote message={error} />
      <div className="field-row">
        <Field label="Amount" error={fieldErrors.amount} hint="Up to 1,000,000">
          <input value={amount} onChange={(event) => setAmount(event.target.value.trim())} inputMode="decimal" required />
        </Field>
        <Field label="Months to repay" error={fieldErrors.duration_months} hint="1 to 60">
          <input type="number" min="1" max="60" value={months} onChange={(event) => setMonths(event.target.value)} required />
        </Field>
      </div>
      <Field label="Reason (optional)" error={fieldErrors.reason}>
        <input value={reason} onChange={(event) => setReason(event.target.value)} />
      </Field>
      <button className="button button-primary" disabled={busy}>
        {busy ? "Submitting..." : "Submit application"}
      </button>
    </form>
  );
}

export default function LoansPage({ user }) {
  const [loans, setLoans] = useState(null);
  const [installments, setInstallments] = useState([]);
  const [wallet, setWallet] = useState(null);
  const [error, setError] = useState("");
  const [paidMessage, setPaidMessage] = useState("");
  const [confirmingId, setConfirmingId] = useState(null);
  const [payingId, setPayingId] = useState(null);

  async function loadData() {
    const [loanData, installmentData, walletData] = await Promise.all([
      getLoans(),
      getUnpaidInstallments(),
      getWallet(),
    ]);
    setLoans(loanData);
    setInstallments(installmentData);
    setWallet(walletData);
  }

  useEffect(() => {
    loadData().catch((err) => setError(err.message));
  }, []);

  async function handlePay(installment) {
    setPayingId(installment.id);
    setError("");
    setPaidMessage("");
    try {
      await payInstallment(installment.id);
      setPaidMessage(`Payment of ${formatMoney(installment.amount, wallet.currency)} received.`);
      await loadData();
    } catch (err) {
      if (err.status === 0 || err.status >= 500) {
        setError("We couldn't confirm this payment. Check your transactions before trying again.");
      } else {
        setError(err.message);
      }
    } finally {
      setPayingId(null);
      setConfirmingId(null);
    }
  }

  if (!loans) {
    return error ? <ErrorNote message={error} /> : <Loading text="Loading your loans..." />;
  }

  return (
    <>
      <h1>Loans</h1>
      <ErrorNote message={error} />
      <SuccessNote message={paidMessage} />

      {user.kyc_status === "verified" ? (
        <ApplyForm onApplied={loadData} />
      ) : (
        <section className="callout">
          <div>
            <div className="callout-title">Verification required</div>
            <p className="muted">Loan applications open once staff have verified your identity.</p>
          </div>
          <a className="button" href="#/kyc">View verification</a>
        </section>
      )}

      {installments.length > 0 && (
        <section>
          <h2>Installments due</h2>
          <ul className="simple-list">
            {installments.map((installment) => (
              <li key={installment.id} className="simple-row">
                <div>
                  <strong>{formatMoney(installment.amount, wallet.currency)}</strong>
                  <span className="muted"> due {formatDate(installment.due_date)}</span>
                </div>
                {confirmingId === installment.id ? (
                  <div className="button-row">
                    <button type="button" className="button button-primary" onClick={() => handlePay(installment)} disabled={payingId !== null}>
                      {payingId === installment.id ? "Paying..." : "Confirm payment"}
                    </button>
                    <button type="button" className="button" onClick={() => setConfirmingId(null)} disabled={payingId !== null}>Cancel</button>
                  </div>
                ) : (
                  <button type="button" className="button" onClick={() => setConfirmingId(installment.id)} disabled={payingId !== null}>Pay</button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2>Your applications</h2>
        {loans.length === 0 ? (
          <p className="empty-state">You haven't applied for a loan yet.</p>
        ) : (
          <ul className="simple-list">
            {loans.map((loan) => (
              <li key={loan.id} className="simple-row">
                <div>
                  <strong>{formatMoney(loan.amount, wallet.currency)}</strong>
                  <span className="muted"> over {loan.duration_months} months · {formatDate(loan.created_at)}</span>
                </div>
                <span className={`badge badge-${STATUS_BADGES[loan.status]}`}>{loan.status}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
