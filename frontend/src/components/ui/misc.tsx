import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

const TONES = {
  info: { icon: Info, cls: "border-sky-500/30 bg-sky-500/10 text-foreground [&_svg]:text-sky-600" },
  warning: { icon: AlertTriangle, cls: "border-amber-500/40 bg-amber-500/10 text-foreground [&_svg]:text-amber-600" },
  error: { icon: XCircle, cls: "border-destructive/40 bg-destructive/10 text-foreground [&_svg]:text-destructive" },
  success: { icon: CheckCircle2, cls: "border-emerald-500/40 bg-emerald-500/10 text-foreground [&_svg]:text-emerald-600" },
} as const;

export function Alert({ tone = "info", title, children, className }: { tone?: keyof typeof TONES; title?: string; children?: ReactNode; className?: string }) {
  const T = TONES[tone];
  return (
    <div role="alert" className={cn("flex gap-3 rounded-lg border p-3 text-sm", T.cls, className)}>
      <T.icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 space-y-0.5">{title && <p className="font-medium">{title}</p>}{children && <div className="text-muted-foreground">{children}</div>}</div>
    </div>
  );
}

export const Separator = ({ className, ...p }: HTMLAttributes<HTMLDivElement>) => <div role="separator" className={cn("h-px w-full bg-border", className)} {...p} />;

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed p-10 text-center">
      {icon && <div className="text-muted-foreground [&_svg]:size-8">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <div className="max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function Table({ className, ...p }: HTMLAttributes<HTMLTableElement>) {
  return <div className="w-full overflow-auto rounded-xl border"><table className={cn("w-full caption-bottom text-sm", className)} {...p} /></div>;
}
export const THead = (p: HTMLAttributes<HTMLTableSectionElement>) => <thead className="bg-muted/50 [&_tr]:border-b" {...p} />;
export const TBody = (p: HTMLAttributes<HTMLTableSectionElement>) => <tbody className="[&_tr:last-child]:border-0" {...p} />;
export const TR = ({ className, ...p }: HTMLAttributes<HTMLTableRowElement>) => <tr className={cn("border-b transition-colors hover:bg-muted/40", className)} {...p} />;
export const TH = ({ className, ...p }: HTMLAttributes<HTMLTableCellElement>) => <th className={cn("h-10 px-3 text-left align-middle text-xs font-semibold uppercase tracking-wide text-muted-foreground", className)} {...p} />;
export const TD = ({ className, ...p }: HTMLAttributes<HTMLTableCellElement>) => <td className={cn("px-3 py-2.5 align-middle", className)} {...p} />;
