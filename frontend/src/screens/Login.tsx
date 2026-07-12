/**
 * Login screen (SPEC 10.3 item 6): POST /api/auth/login, honest error
 * states, role shown immediately after a successful sign-in. Keeps the
 * navy + serif brand hero from the Milestone 1 shell.
 */

import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";
import { ApiError, isAuthenticated, login } from "../lib/api";

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signedInAs, setSignedInAs] = useState<string | null>(null);

  const from =
    (location.state as { from?: string } | null)?.from ?? "/";

  if (isAuthenticated() && signedInAs === null) {
    // Already holding a session in this tab: no second login needed.
    navigate(from, { replace: true });
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const user = await login(username, password);
      setSignedInAs(`${user.username} (${user.role})`);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 401
            ? "Invalid username or password."
            : `Login failed (HTTP ${err.status}): ${err.detail}`,
        );
      } else {
        setError(
          `API unreachable: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="login-page">
      <header className="login-hero">
        <h1>Paritran</h1>
        <p>From complaint to conviction</p>
      </header>

      <form className="login-card card" onSubmit={(e) => void onSubmit(e)}>
        <h3>Sign in</h3>
        <div>
          <label className="field-label" htmlFor="login-username">
            Username
          </label>
          <input
            id="login-username"
            className="input"
            style={{ width: "100%" }}
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="field-label" htmlFor="login-password">
            Password
          </label>
          <input
            id="login-password"
            className="input"
            style={{ width: "100%" }}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error !== null && (
          <div className="error-box" role="alert">
            {error}
          </div>
        )}
        {signedInAs !== null && (
          <div className="notice-box" role="status">
            Signed in as <span className="mono">{signedInAs}</span>
          </div>
        )}
        <button
          type="submit"
          className="btn btn-primary"
          disabled={pending || username === "" || password === ""}
        >
          {pending ? "Signing in" : "Sign in"}
        </button>
        <p className="muted small" style={{ margin: 0 }}>
          Roles: officer, supervisor, auditor (seeded users, SPEC section 5).
        </p>
      </form>

      <footer className="footer" style={{ border: "none" }}>
        Paritran . From complaint to conviction . PS-69EEFE4F8CD1C
      </footer>
    </div>
  );
}
