import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold transition-colors", {
  variants: {
    variant: {
      default: "border-transparent bg-primary text-primary-foreground",
      secondary: "border-transparent bg-secondary text-secondary-foreground",
      outline: "text-foreground",
      brand: "border-transparent bg-brand text-brand-foreground",
      destructive: "border-transparent bg-destructive/10 text-destructive",
      success: "border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
      warning: "border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400",
      critical: "border-transparent bg-severity-critical text-white",
      high: "border-transparent bg-severity-high text-white",
      medium: "border-transparent bg-severity-medium text-white",
      low: "border-transparent bg-severity-low text-white",
      none: "border-transparent bg-severity-none text-white",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export type Rating = "Critical" | "High" | "Medium" | "Low" | "None" | "";
const RATING_VARIANT = { Critical: "critical", High: "high", Medium: "medium", Low: "low", None: "none", "": "outline" } as const;

export function RatingBadge({ rating, score }: { rating: string; score?: number | null }) {
  const r = (rating in RATING_VARIANT ? rating : "") as Rating;
  return <Badge variant={RATING_VARIANT[r]}>{r ? `${r}${score != null ? ` ${score}` : ""}` : "sin CVSS"}</Badge>;
}
