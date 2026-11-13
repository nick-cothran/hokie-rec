import "../styles/SignIn.css";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { fullName, useAuth } from "../auth";
import { accountDestination, accountLink } from "../authNavigation";
import ChangePassword from "./ChangePassword";

function SignIn() {
  const { user, loading, error: sessionError, signIn, signOut } = useAuth();
  const [pid, setPid] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [params] = useSearchParams();
  const navigate = useNavigate();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const current = await signIn(pid, password);
      setPassword("");
      navigate(accountDestination(params.get("next"), current.role), {
        replace: true,
      });
    } catch (failure) {
      setError((failure as Error).message);
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    setError("");
    try {
      await signOut();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="signin-page">
      <section className="signin-panel">
        <h1>{user ? "Your account" : "Welcome back."}</h1>
        {loading ? (
          <p role="status">Checking your session…</p>
        ) : user ? (
          <div className="signin-form">
            <p>
              Signed in as <strong>{fullName(user)}</strong> ({user.role}).
            </p>
            <Link className="button button-primary" to="/profile">
              Edit profile
            </Link>
            <Link className="button button-primary" to="/teams">
              Go to teams
            </Link>
            {user.role === "admin" && (
              <Link className="button button-outline" to="/admin/users">
                Manage accounts
              </Link>
            )}
            <button
              className="button button-outline"
              type="button"
              disabled={busy}
              onClick={logout}
            >
              {busy ? "Signing out…" : "Sign out"}
            </button>
            <ChangePassword />
          </div>
        ) : (
          <>
            <p>Sign in with your VT PID and password to access your account.</p>
            <form className="signin-form" onSubmit={submit}>
              <label className="field">
                PID
                <input
                  name="username"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={pid}
                  onChange={(e) => setPid(e.target.value)}
                  maxLength={40}
                  required
                  disabled={busy}
                />
              </label>
              <label className="field">
                Password
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  maxLength={128}
                  required
                  disabled={busy}
                />
              </label>
              <button
                className="button button-primary"
                type="submit"
                disabled={busy || !pid.trim() || !password}
              >
                {busy ? "Signing in…" : "Sign in"}
              </button>
            </form>
            <p className="signin-help">
              New to Hokie Rec?{" "}
              <Link to={accountLink("/sign-up", params.get("next"))}>
                Create an account
              </Link>
              .
            </p>
          </>
        )}
        {(error || sessionError) && (
          <p className="notice notice-error" role="alert">
            {error || sessionError}
          </p>
        )}
        <p className="signin-help">
          Just looking around?{" "}
          <Link to="/leagues">Browse leagues without signing in</Link>.
        </p>
      </section>
    </main>
  );
}

export default SignIn;
