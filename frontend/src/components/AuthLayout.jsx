export default function AuthLayout({ title, intro, children }) {
  return (
    <main className="auth-page">
      <div className="auth-brand">
        <p className="brand">Banking App</p>
        <p className="auth-tagline">Every balance change is locked, recorded and checked.</p>
      </div>
      <section className="auth-card">
        <h1>{title}</h1>
        {intro && <p className="muted">{intro}</p>}
        {children}
      </section>
    </main>
  );
}
