/**
 * Route guard: no access token in sessionStorage means straight to
 * /login (the intended destination rides along in location state so
 * login can send the user back).
 */

import { useSyncExternalStore, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { getAccessToken, subscribeAuth } from "../lib/api";

export function RequireAuth({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(subscribeAuth, getAccessToken);
  const location = useLocation();

  if (token === null) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  return <>{children}</>;
}
