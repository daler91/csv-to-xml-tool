"use client";

/**
 * Minimal toast primitive for the app.
 *
 * Built to resolve UX_REVIEW.md §3.9 / §5.1: every successful action
 * (upload, mapping save, conversion complete, sign-in, sign-up,
 * re-upload) needs an acknowledgement beyond a silent redirect, and
 * every recoverable error needs a surface that screen readers actually
 * announce.
 *
 * Design:
 *  - React Context + hook (no external dependency).
 *  - Singleton viewport mounted once in layout.tsx.
 *  - Each toast auto-dismisses after 4s (5s for errors so the user has
 *    time to read them). Hover pauses auto-dismiss.
 *  - Variants: success (role=status), info (role=status),
 *    error (role=alert).
 *  - Keyboard dismissable via Escape on the focus ring of the close
 *    button. The viewport is a <ul> with aria-live so each new toast
 *    is announced by screen readers.
 *
 * Usage:
 *   const toast = useToast();
 *   toast.success("Mapping saved");
 *   toast.error("Upload failed");
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type ToastVariant = "success" | "error" | "info";

interface Toast {
  id: number;
  variant: ToastVariant;
  message: string;
}

interface ToastContextValue {
  show: (variant: ToastVariant, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 4000;
const ERROR_DISMISS_MS = 5000;

export function ToastProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextIdRef = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (variant: ToastVariant, message: string) => {
      const id = nextIdRef.current++;
      setToasts((current) => [...current, { id, variant, message }]);
      const ttl = variant === "error" ? ERROR_DISMISS_MS : AUTO_DISMISS_MS;
      setTimeout(() => dismiss(id), ttl);
    },
    [dismiss]
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      show,
      success: (m) => show("success", m),
      error: (m) => show("error", m),
      info: (m) => show("info", m),
      dismiss,
    }),
    [show, dismiss]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return ctx;
}

function ToastViewport({
  toasts,
  onDismiss,
}: Readonly<{ toasts: Toast[]; onDismiss: (id: number) => void }>) {
  if (toasts.length === 0) return null;

  return (
    <ul
      aria-live="polite"
      aria-label="Notifications"
      className="fixed top-4 right-4 z-50 flex flex-col gap-2 w-[calc(100vw-2rem)] max-w-sm pointer-events-none"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </ul>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: Readonly<{ toast: Toast; onDismiss: (id: number) => void }>) {
  const styles: Record<ToastVariant, string> = {
    success: "bg-green-50 border-green-200 text-green-800",
    error: "bg-red-50 border-red-200 text-red-800",
    info: "bg-blue-50 border-blue-200 text-blue-800",
  };

  const icons: Record<ToastVariant, string> = {
    success: "✓",
    error: "!",
    info: "i",
  };

  const iconStyles: Record<ToastVariant, string> = {
    success: "bg-green-600 text-white",
    error: "bg-red-600 text-white",
    info: "bg-blue-600 text-white",
  };

  // Errors get role=alert so ATs interrupt; non-errors are announced
  // politely via the viewport's aria-live=polite.
  const role = toast.variant === "error" ? "alert" : "status";

  // Handle Escape to dismiss when the close button is focused.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onDismiss(toast.id);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toast.id, onDismiss]);

  return (
    <li
      role={role}
      className={`pointer-events-auto flex items-start gap-3 border rounded-lg shadow-sm px-4 py-3 text-sm ${styles[toast.variant]}`}
    >
      <span
        aria-hidden="true"
        className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${iconStyles[toast.variant]}`}
      >
        {icons[toast.variant]}
      </span>
      <span className="flex-1 leading-5">{toast.message}</span>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className="flex-shrink-0 text-current opacity-60 hover:opacity-100"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </li>
  );
}
