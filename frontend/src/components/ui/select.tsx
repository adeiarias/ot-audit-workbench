import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";

import { cn } from "@/lib/utils";

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = forwardRef<ElementRef<typeof SelectPrimitive.Trigger>, ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>>(({ className, children, ...p }, ref) => (
  <SelectPrimitive.Trigger ref={ref} className={cn("flex h-9 w-full items-center justify-between gap-2 whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground [&>span]:truncate", className)} {...p}>
    {children}
    <SelectPrimitive.Icon asChild><ChevronDown className="size-4 shrink-0 opacity-50" /></SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = "SelectTrigger";

export const SelectContent = forwardRef<ElementRef<typeof SelectPrimitive.Content>, ComponentPropsWithoutRef<typeof SelectPrimitive.Content>>(({ className, children, position = "popper", ...p }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content ref={ref} position={position} className={cn("relative z-50 max-h-80 min-w-[8rem] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0", position === "popper" && "data-[side=bottom]:translate-y-1 data-[side=top]:-translate-y-1", className)} {...p}>
      <SelectPrimitive.Viewport className={cn("p-1", position === "popper" && "w-full min-w-[var(--radix-select-trigger-width)]")}>{children}</SelectPrimitive.Viewport>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = "SelectContent";

export const SelectItem = forwardRef<ElementRef<typeof SelectPrimitive.Item>, ComponentPropsWithoutRef<typeof SelectPrimitive.Item>>(({ className, children, ...p }, ref) => (
  <SelectPrimitive.Item ref={ref} className={cn("relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50", className)} {...p}>
    <span className="absolute right-2 flex size-3.5 items-center justify-center"><SelectPrimitive.ItemIndicator><Check className="size-4" /></SelectPrimitive.ItemIndicator></span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
));
SelectItem.displayName = "SelectItem";

/** Select sencillo a partir de una lista de opciones (value "" no está permitido por Radix: usa un valor centinela). */
export function SimpleSelect({ value, onChange, options, placeholder, className, disabled }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; placeholder?: string; className?: string; disabled?: boolean;
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className={className}><SelectValue placeholder={placeholder} /></SelectTrigger>
      <SelectContent>{options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
    </Select>
  );
}
