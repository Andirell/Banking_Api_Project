const NAV_LINKS = [
  { page: "dashboard", label: "Overview" },
  { page: "send", label: "Send money" },
  { page: "loans", label: "Loans" },
  { page: "kyc", label: "Verification" },
];

export default function AppLayout({ page, user, onSignOut, children }) {
  return (
    <div className="app-shell">
      <header className="top-bar">
        <a className="brand" href="#/dashboard">Banking App</a>
        <nav aria-label="Main">
          {NAV_LINKS.map((link) => (
            <a
              key={link.page}
              href={`#/${link.page}`}
              className={page === link.page ? "nav-link nav-link-active" : "nav-link"}
              aria-current={page === link.page ? "page" : undefined}
            >
              {link.label}
            </a>
          ))}
        </nav>
        <div className="top-bar-user">
          <span className="muted user-name">{user.first_name}</span>
          <button type="button" className="link-button" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      <main className="page">{children}</main>
    </div>
  );
}
