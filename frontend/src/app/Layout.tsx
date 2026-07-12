/**
 * Authenticated shell (SPEC 10.3): left nav with the five screens, the
 * global System Status widget at the bottom of the nav, header with the
 * signed-in user's role, footer brand line, and the Cmd+K palette.
 */

import { useEffect, useState, useSyncExternalStore } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { getUser, logout, subscribeAuth } from "../lib/api";
import { CommandPalette } from "./CommandPalette";
import { StatusWidget } from "./StatusWidget";
import { ToastHost } from "./toasts";

interface NavItem {
  label: string;
  to: string;
  end?: boolean;
  tag?: string;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Discovery", to: "/", end: true },
  { label: "Demo", to: "/demo", tag: "SPEC 14" },
  { label: "Case File", to: "/casefile", tag: "M6" },
  { label: "Custody", to: "/custody", tag: "M6" },
  { label: "Evaluation", to: "/evaluation" },
  { label: "Security", to: "/security", tag: "M7" },
];

function titleFor(pathname: string): string {
  if (pathname.startsWith("/demo")) return "Guided Demo";
  if (pathname.startsWith("/casefile")) return "Case File";
  if (pathname.startsWith("/custody")) return "Custody Ledger";
  if (pathname.startsWith("/evaluation")) return "Evaluation";
  if (pathname.startsWith("/security")) return "Security Posture";
  return "Discovery & Triage";
}

export function Layout() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const user = useSyncExternalStore(subscribeAuth, getUser);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="shell">
      <nav className="nav" aria-label="Primary">
        <div className="nav-brand">
          <h1>Paritran</h1>
          <p>From complaint to conviction</p>
        </div>
        <ul className="nav-links">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.end} className="nav-link">
                <span>{item.label}</span>
                {item.tag !== undefined && (
                  <span className="nav-tag">{item.tag}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="nav-spacer" />
        <StatusWidget />
        <div className="nav-user">
          <span>
            <span className="mono small">{user?.username ?? "unknown"}</span>{" "}
            <span className="role-chip">{user?.role ?? "?"}</span>
          </span>
          <button
            type="button"
            className="kbd-hint"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            logout
          </button>
        </div>
      </nav>

      <div className="main">
        <header className="main-header">
          <h2>{titleFor(location.pathname)}</h2>
          <button
            type="button"
            className="kbd-hint"
            onClick={() => setPaletteOpen(true)}
            aria-label="Open command palette"
          >
            Cmd+K
          </button>
        </header>
        <main className="main-body">
          <Outlet />
        </main>
        <footer className="footer">
          Paritran . From complaint to conviction . PS-69EEFE4F8CD1C
        </footer>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <ToastHost />
    </div>
  );
}
