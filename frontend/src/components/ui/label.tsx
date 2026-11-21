import * as LabelPrimitive from "@radix-ui/react-label";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";

import { cn } from "@/lib/utils";

export const Label = forwardRef<ElementRef<typeof LabelPrimitive.Root>, ComponentPropsWithoutRef<typeof LabelPrimitive.Root>>(({ className, ...p }, ref) => (
  <LabelPrimitive.Root ref={ref} className={cn("text-sm font-medium leading-none peer-disabled:opacity-70", className)} {...p} />
));
Label.displayName = "Label";

/** Etiqueta + control + ayuda/error apilados. */
export function Field({ label, hint, error, children, className }: { label: string; hint?: string; error?: string | null; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      <Label>{label}</Label>
      {children}
      {hint && !error && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
