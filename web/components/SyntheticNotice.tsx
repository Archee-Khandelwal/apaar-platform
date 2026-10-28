/** The always-visible, low-key reminder that nothing on screen is real. */
import { cn } from "@/lib/utils";

export function SyntheticNotice({ className }: { className?: string }) {
  return (
    <p className={cn("px-4 py-4 text-center text-[11px] text-muted-foreground", className)}>
      SIH 2026 prototype — all data shown is synthetic.
    </p>
  );
}
