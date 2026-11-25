export function Field({ label, error, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && !error && <span className="field-hint">{hint}</span>}
      {error && <span className="field-error">{error}</span>}
    </label>
  );
}

export function ErrorNote({ message }) {
  if (!message) {
    return null;
  }
  return <p className="note note-error" role="alert">{message}</p>;
}

export function SuccessNote({ message }) {
  if (!message) {
    return null;
  }
  return <p className="note note-success" role="status">{message}</p>;
}

export function Loading({ text = "Loading..." }) {
  return <p className="loading" role="status">{text}</p>;
}
