import * as T from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const TooltipProvider = T.Provider;

export function Tip({ content, children, side = "right", className }: { content: ReactNode; children: ReactNode; side?: "top" | "right" | "bottom" | "left"; className?: string }) {
  return (
    <T.Root delayDuration={150}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6} className={cn("z-50 max-w-xs rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground shadow-md animate-in fade-in-0", className)}>{content}</T.Content>
      </T.Portal>
    </T.Root>
  );
}
