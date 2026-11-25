import { formatDate, formatMoney } from "../lib/format.js";

function isMoneyIn(transaction, myEmail) {
  if (transaction.transaction_type === "deposit") {
    return true;
  }
  if (transaction.transaction_type === "withdraw") {
    return false;
  }
  return transaction.receiver === myEmail;
}

function getTitle(transaction, moneyIn) {
  if (transaction.transaction_type === "deposit") {
    return "Deposit";
  }
  if (transaction.transaction_type === "withdraw") {
    return "Withdrawal";
  }
  if (moneyIn) {
    return `From ${transaction.sender}`;
  }
  return `To ${transaction.receiver}`;
}

export default function TransactionList({ transactions, myEmail, currency }) {
  if (transactions.length === 0) {
    return <p className="empty-state">No transactions yet. They will appear here as soon as money moves.</p>;
  }

  return (
    <ul className="transaction-list">
      {transactions.map((transaction) => {
        const moneyIn = isMoneyIn(transaction, myEmail);
        return (
          <li key={transaction.id} className="transaction-row">
            <div className="transaction-main">
              <span className="transaction-title">{getTitle(transaction, moneyIn)}</span>
              <span className="muted transaction-detail">
                {formatDate(transaction.created_at)}
                {transaction.description ? ` · ${transaction.description}` : ""}
              </span>
            </div>
            <div className="transaction-side">
              <span className={moneyIn ? "amount amount-in" : "amount"}>
                {moneyIn ? "+" : "−"}{formatMoney(transaction.amount, currency)}
              </span>
              {transaction.status !== "successful" && (
                <span className="badge badge-waiting">{transaction.status}</span>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
