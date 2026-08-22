import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle, Info, WarningCircle, X } from "@phosphor-icons/react";

export type ToastKind = "success" | "error" | "info";

export interface ToastOptions {
  kind?: ToastKind;
  duration?: number;
}

interface ToastRecord {
  id: string;
  message: string;
  kind: ToastKind;
  state: "open" | "closing";
}

interface ToastContextValue {
  notify: (message: string, options?: ToastOptions) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

function iconFor(kind: ToastKind) {
  if (kind === "success") return <CheckCircle weight="fill" size={19} />;
  if (kind === "error") return <WarningCircle weight="fill" size={19} />;
  return <Info weight="fill" size={19} />;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef(new Map<string, number>());

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.map((toast) => toast.id === id ? { ...toast, state: "closing" } : toast));
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 180);
  }, []);

  const notify = useCallback((message: string, options?: ToastOptions) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const duration = options?.duration ?? 3600;
    const toast: ToastRecord = { id, message, kind: options?.kind ?? "info", state: "open" };
    setToasts((current) => [...current.slice(-3), toast]);
    const timer = window.setTimeout(() => dismiss(id), duration);
    timers.current.set(id, timer);
    return id;
  }, [dismiss]);

  useEffect(() => () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current.clear();
  }, []);

  return (
    <ToastContext.Provider value={{ notify, dismiss }}>
      {children}
      <div className="core-toast-viewport" aria-live="polite" aria-atomic="false">
        {toasts.map((toast) => (
          <div className="core-toast" data-kind={toast.kind} data-state={toast.state} key={toast.id} role={toast.kind === "error" ? "alert" : "status"}>
            <span className="core-toast-icon">{iconFor(toast.kind)}</span>
            <span className="core-toast-message">{toast.message}</span>
            <button type="button" className="core-toast-close" aria-label="关闭通知" onClick={() => dismiss(toast.id)}><X size={16} /></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}

/**
 * Compatibility helper for pages that previously rendered an inline Radix
 * Callout. Rendering this component emits the same message through the
 * application-wide top notification and deliberately leaves no inline block.
 */
export function ToastNotice({ message, kind = "info" }: { message?: string; kind?: ToastKind }) {
  const { notify } = useToast();
  useEffect(() => {
    if (message) notify(message, { kind });
  }, [kind, message, notify]);
  return null;
}
