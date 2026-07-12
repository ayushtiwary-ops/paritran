/**
 * Honest route error boundary (SPEC 10.4: no dead ends, no white screen).
 *
 * react-router renders this whenever a route element throws during render
 * or a loader/action rejects. Without it an unhandled throw blanks the
 * page; here the user gets a readable explanation, the actual error text
 * (never a hidden failure), and a way back into the app. It carries no
 * engine data, so it never invents a number.
 */

import { isRouteErrorResponse, useNavigate, useRouteError } from "react-router";

function describe(error: unknown): { heading: string; detail: string } {
  if (isRouteErrorResponse(error)) {
    return {
      heading: `${error.status} ${error.statusText}`,
      detail:
        typeof error.data === "string"
          ? error.data
          : "This route could not be rendered.",
    };
  }
  if (error instanceof Error) {
    return { heading: "Something broke on this screen", detail: error.message };
  }
  return {
    heading: "Something broke on this screen",
    detail: String(error),
  };
}

export function RouteError() {
  const error = useRouteError();
  const navigate = useNavigate();
  const { heading, detail } = describe(error);

  return (
    <div className="login-page" role="alert">
      <div className="card" style={{ maxWidth: "34rem", width: "min(34rem, 92vw)" }}>
        <h3>{heading}</h3>
        <p className="small" style={{ marginTop: 0 }}>
          The screen hit an error and stopped rendering rather than showing
          you a blank page. Nothing here is fabricated; the message below is
          the real failure.
        </p>
        <p className="error-box small mono" style={{ marginBottom: 0 }}>
          {detail}
        </p>
        <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.9rem" }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate("/")}
          >
            Back to Discovery
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </div>
      </div>
    </div>
  );
}
