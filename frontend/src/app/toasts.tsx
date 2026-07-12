/**
 * Minimal toast system. Two live regions: polite for routine updates,
 * assertive for decision results and critical alerts (SPEC 10.4).
 */

import { useEffect, useState } from "react";

export interface Toast {
  id: number;
  title: string;
  detail?: string;
  tone: "info" | "success" | "danger";
  assertive?: boolean;
}

type ToastInput = Omit<Toast, "id">;

const TOAST_TTL_MS = 7000;

let nextId = 1;
let toasts: Toast[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  for (const fn of listeners) fn();
}

export function pushToast(input: ToastInput): void {
  const toast: Toast = { ...input, id: nextId++ };
  toasts = [...toasts, toast];
  emit();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== toast.id);
    emit();
  }, TOAST_TTL_MS);
}

export function ToastHost() {
  const [items, setItems] = useState<Toast[]>(toasts);

  useEffect(() => {
    const listener = () => setItems(toasts);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const polite = items.filter((t) => !t.assertive);
  const assertive = items.filter((t) => t.assertive);

  const render = (toast: Toast) => (
    <div key={toast.id} className={`toast ${toast.tone}`}>
      <strong>{toast.title}</strong>
      {toast.detail !== undefined && (
        <span className="toast-detail">{toast.detail}</span>
      )}
    </div>
  );

  return (
    <div className="toast-region">
      <div aria-live="polite" role="status">
        {polite.map(render)}
      </div>
      <div aria-live="assertive" role="alert">
        {assertive.map(render)}
      </div>
    </div>
  );
}
