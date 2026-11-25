import { useEffect, useState } from "react";
import { getTransactions, getWallet } from "../lib/api.js";
import { formatMoney } from "../lib/format.js";
import { ErrorNote, Loading } from "./FormParts.jsx";
import { getKycSummary, KycBadge } from "./KycStatus.jsx";
import TransactionList from "./TransactionList.jsx";

export default function DashboardPage({ user }) {
  const [wallet, setWallet] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let stillOnPage = true;

    async function loadData() {
      try {
        const [walletData, transactionData] = await Promise.all([getWallet(), getTransactions()]);
        if (stillOnPage) {
          setWallet(walletData);
          setTransactions(transactionData);
        }
      } catch (err) {
        if (stillOnPage) {
          setError(err.message);
        }
      }
    }

    loadData();
    return () => {
      stillOnPage = false;
    };
  }, []);

  if (error) {
    return <ErrorNote message={error} />;
  }
  if (!wallet) {
    return <Loading text="Loading your account..." />;
  }

  const kyc = getKycSummary(user);
  const walletIsEmpty = Number(wallet.balance) === 0;

  return (
    <>
      <section className="balance-panel">
        <div>
          <p className="balance-label">Available balance</p>
          <p className="balance-amount">{formatMoney(wallet.balance, wallet.currency)}</p>
          {walletIsEmpty && (
            <p className="balance-note">Deposits are recorded by staff once funds arrive, or when a loan is approved.</p>
          )}
        </div>
        <a className="button button-on-dark" href="#/send">Send money</a>
      </section>

      {user.kyc_status !== "verified" && (
        <section className="callout">
          <div>
            <div className="callout-title">Identity verification <KycBadge user={user} /></div>
            <p className="muted">{kyc.text}</p>
          </div>
          <a className="button" href="#/kyc">View verification</a>
        </section>
      )}

      <section>
        <h2>Transactions</h2>
        <TransactionList transactions={transactions} myEmail={user.email} currency={wallet.currency} />
      </section>
    </>
  );
}
