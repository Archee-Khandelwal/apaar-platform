"use client";

/** A deliberately small toast: one queue, auto-dismiss, no dependency. */
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

type Tone = "info" | "success" | "warning" | "danger";
interface Toast {
  id: number;
  message: string;
  tone: Tone;
}

const ToastContext = createContext<{ toast: (message: string, tone?: Tone) => void } | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((message: string, tone: Tone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 6000);
  }, []);

  const value = useMemo(() => ({ toast }), [toast]);
  const tones: Record<Tone, string> = {
    info: "border-slate-300 bg-slate-900 text-white",
    success: "border-emerald-300 bg-emerald-700 text-white",
    warning: "border-amber-300 bg-amber-600 text-white",
    danger: "border-red-300 bg-red-700 text-white",
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
        {toasts.map((item) => (
          <div
            key={item.id}
            role="status"
            className={cn(
              "pointer-events-auto rounded-md border px-4 py-3 text-sm shadow-lg animate-in slide-in-from-bottom-2",
              tones[item.tone],
            )}
          >
            {item.message}
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
