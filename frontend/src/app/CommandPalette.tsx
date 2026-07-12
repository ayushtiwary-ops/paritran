/**
 * cmdk command palette (SPEC 10.2): Cmd+K / Ctrl+K.
 *
 * Actions: jump to any screen, start the seed-42 stub run, start a
 * judge's-seed run (numeric input page; any seed reruns the full
 * engine), and logout. Run starts POST /api/intake/run and route to
 * Discovery with ?run=<id> so the screen subscribes to the SSE stream.
 */

import { Command } from "cmdk";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, logout, startRun } from "../lib/api";
import { pushToast } from "./toasts";

interface PaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SCREENS: { label: string; to: string }[] = [
  { label: "Discovery & Triage", to: "/" },
  { label: "Case File", to: "/casefile" },
  { label: "Custody Ledger", to: "/custody" },
  { label: "Evaluation", to: "/evaluation" },
  { label: "Security Posture", to: "/security" },
];

const DEFAULT_SEED = 42;

export function CommandPalette({ open, onOpenChange }: PaletteProps) {
  const navigate = useNavigate();
  const [page, setPage] = useState<"root" | "seed">("root");
  const [search, setSearch] = useState("");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!open) {
      setPage("root");
      setSearch("");
    }
  }, [open]);

  const launchRun = useCallback(
    async (seed: number) => {
      if (starting) return;
      setStarting(true);
      try {
        const started = await startRun(seed, "stub");
        onOpenChange(false);
        pushToast({
          title: `Run started (seed ${started.seed}, ${started.generator})`,
          detail: started.run_id,
          tone: "info",
        });
        navigate(`/?run=${encodeURIComponent(started.run_id)}`);
      } catch (error) {
        pushToast({
          title: "Run failed to start",
          detail:
            error instanceof ApiError ? error.detail : String(error),
          tone: "danger",
          assertive: true,
        });
      } finally {
        setStarting(false);
      }
    },
    [navigate, onOpenChange, starting],
  );

  const seedValue = Number.parseInt(search.trim(), 10);
  const seedValid = Number.isSafeInteger(seedValue);

  return (
    <>
      {open && (
        <div
          className="palette-overlay"
          onClick={() => onOpenChange(false)}
          aria-hidden="true"
        />
      )}
      <Command.Dialog
        open={open}
        onOpenChange={onOpenChange}
        label="Command palette"
        shouldFilter={page === "root"}
        onKeyDown={(event) => {
          if (page === "seed" && (event.key === "Escape" || (event.key === "Backspace" && search === ""))) {
            event.preventDefault();
            setPage("root");
            setSearch("");
          }
        }}
      >
        <Command.Input
          value={search}
          onValueChange={setSearch}
          placeholder={
            page === "seed"
              ? "Type any seed (integer), then press Enter"
              : "Type a command or search"
          }
          inputMode={page === "seed" ? "numeric" : "text"}
        />
        <Command.List>
          {page === "root" && (
            <>
              <Command.Empty>No matching command.</Command.Empty>
              <Command.Group heading="Screens">
                {SCREENS.map((screen) => (
                  <Command.Item
                    key={screen.to}
                    onSelect={() => {
                      onOpenChange(false);
                      navigate(screen.to);
                    }}
                  >
                    Go to {screen.label}
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group heading="Pipeline">
                <Command.Item
                  disabled={starting}
                  onSelect={() => void launchRun(DEFAULT_SEED)}
                >
                  Start seed-{DEFAULT_SEED} run (stub)
                  <span className="hint">POST /api/intake/run</span>
                </Command.Item>
                <Command.Item
                  onSelect={() => {
                    setPage("seed");
                    setSearch("");
                  }}
                >
                  Start judge&apos;s-seed run
                  <span className="hint">any seed, live rerun</span>
                </Command.Item>
              </Command.Group>
              <Command.Group heading="Session">
                <Command.Item
                  onSelect={() => {
                    onOpenChange(false);
                    logout();
                    navigate("/login");
                  }}
                >
                  Logout
                </Command.Item>
              </Command.Group>
            </>
          )}
          {page === "seed" && (
            <Command.Group heading="Judge's seed">
              <Command.Item
                disabled={!seedValid || starting}
                onSelect={() => {
                  if (seedValid) void launchRun(seedValue);
                }}
              >
                {seedValid
                  ? `Start stub run with seed ${seedValue}`
                  : "Enter an integer seed to enable"}
                <span className="hint">every metric moves with it</span>
              </Command.Item>
              <Command.Item
                onSelect={() => {
                  setPage("root");
                  setSearch("");
                }}
              >
                Back
              </Command.Item>
            </Command.Group>
          )}
        </Command.List>
      </Command.Dialog>
    </>
  );
}
