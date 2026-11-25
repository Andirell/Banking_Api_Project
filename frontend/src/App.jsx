import { useEffect, useState } from "react";
import { getProfile, hasSession, setApiListeners, signOut } from "./lib/api.js";
import AppLayout from "./components/AppLayout.jsx";
import DashboardPage from "./components/DashboardPage.jsx";
import ForgotPasswordPage from "./components/ForgotPasswordPage.jsx";
import { ErrorNote, Loading } from "./components/FormParts.jsx";
import KycPage from "./components/KycPage.jsx";
import LoansPage from "./components/LoansPage.jsx";
import SendMoneyPage from "./components/SendMoneyPage.jsx";
import SignInPage from "./components/SignInPage.jsx";
import SignUpPage from "./components/SignUpPage.jsx";

function getPageFromAddress() {
  return window.location.hash.replace("#/", "");
}

function goToPage(page) {
  window.location.hash = `#/${page}`;
}

export default function App() {
  const [page, setPage] = useState(getPageFromAddress());
  const [user, setUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(hasSession());
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [serverIsSlow, setServerIsSlow] = useState(false);

  async function loadUser() {
    setLoadError("");
    try {
      setUser(await getProfile());
    } catch (err) {
      // A 401 already went through onSessionExpired. Anything else is the server
      // or network, so keep the session and let the user try again.
      if (err.status !== 401) {
        setLoadError(err.message);
      }
    } finally {
      setCheckingSession(false);
    }
  }

  useEffect(() => {
    function handleAddressChange() {
      setPage(getPageFromAddress());
      window.scrollTo(0, 0);
    }

    setApiListeners({
      onSessionExpired: () => {
        setUser(null);
        setNotice("Your session has ended. Please sign in again.");
      },
      onSlowChange: setServerIsSlow,
    });
    window.addEventListener("hashchange", handleAddressChange);

    if (hasSession()) {
      loadUser();
    }
    return () => window.removeEventListener("hashchange", handleAddressChange);
  }, []);

  async function handleSignOut() {
    try {
      await signOut();
    } catch {
      // This browser's tokens are already cleared, which is what the user asked for.
    }
    setUser(null);
    setNotice("");
    goToPage("signin");
  }

  function renderPage() {
    if (checkingSession) {
      return <main className="auth-page"><Loading text="Opening your account..." /></main>;
    }

    if (loadError) {
      return (
        <main className="auth-page">
          <section className="auth-card">
            <ErrorNote message={loadError} />
            <button type="button" className="button button-primary" onClick={loadUser}>Try again</button>
          </section>
        </main>
      );
    }

    if (!user) {
      if (page === "signup") {
        return (
          <SignUpPage
            onSignedUp={() => {
              setNotice("Account created. Sign in to continue.");
              goToPage("signin");
            }}
          />
        );
      }
      if (page === "forgot-password") {
        return (
          <ForgotPasswordPage
            onPasswordReset={() => {
              setNotice("Password updated. Sign in with your new password.");
              goToPage("signin");
            }}
          />
        );
      }
      return (
        <SignInPage
          key={notice}
          notice={notice}
          onSignedIn={async () => {
            setNotice("");
            await loadUser();
            goToPage("dashboard");
          }}
        />
      );
    }

    let content = <DashboardPage user={user} />;
    if (page === "send") {
      content = <SendMoneyPage />;
    } else if (page === "loans") {
      content = <LoansPage user={user} />;
    } else if (page === "kyc") {
      content = <KycPage user={user} onSubmitted={loadUser} />;
    }

    const activePage = ["send", "loans", "kyc"].includes(page) ? page : "dashboard";
    return (
      <AppLayout page={activePage} user={user} onSignOut={handleSignOut}>
        {content}
      </AppLayout>
    );
  }

  return (
    <>
      {serverIsSlow && (
        <p className="slow-banner" role="status">The server is waking up. This can take up to a minute.</p>
      )}
      {renderPage()}
    </>
  );
}
