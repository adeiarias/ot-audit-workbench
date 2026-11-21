import * as M from "@radix-ui/react-dropdown-menu";
import { Check } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from "react";

import { cn } from "@/lib/utils";

export const DropdownMenu = M.Root;
export const DropdownMenuTrigger = M.Trigger;
export const DropdownMenuGroup = M.Group;
export const DropdownMenuRadioGroup = M.RadioGroup;

export const DropdownMenuContent = forwardRef<ElementRef<typeof M.Content>, ComponentPropsWithoutRef<typeof M.Content>>(({ className, sideOffset = 6, ...p }, ref) => (
  <M.Portal>
    <M.Content ref={ref} sideOffset={sideOffset} className={cn("z-50 min-w-[10rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0", className)} {...p} />
  </M.Portal>
));
DropdownMenuContent.displayName = "DropdownMenuContent";

export const DropdownMenuItem = forwardRef<ElementRef<typeof M.Item>, ComponentPropsWithoutRef<typeof M.Item>>(({ className, ...p }, ref) => (
  <M.Item ref={ref} className={cn("relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4", className)} {...p} />
));
DropdownMenuItem.displayName = "DropdownMenuItem";

export const DropdownMenuRadioItem = forwardRef<ElementRef<typeof M.RadioItem>, ComponentPropsWithoutRef<typeof M.RadioItem>>(({ className, children, ...p }, ref) => (
  <M.RadioItem ref={ref} className={cn("relative flex cursor-default select-none items-center gap-2 rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-accent focus:text-accent-foreground", className)} {...p}>
    {children}
    <span className="absolute right-2 flex size-3.5 items-center justify-center"><M.ItemIndicator><Check className="size-4" /></M.ItemIndicator></span>
  </M.RadioItem>
));
DropdownMenuRadioItem.displayName = "DropdownMenuRadioItem";

export const DropdownMenuLabel = ({ className, ...p }: ComponentPropsWithoutRef<typeof M.Label>) => <M.Label className={cn("px-2 py-1.5 text-xs font-semibold text-muted-foreground", className)} {...p} />;
export const DropdownMenuSeparator = ({ className, ...p }: ComponentPropsWithoutRef<typeof M.Separator>) => <M.Separator className={cn("-mx-1 my-1 h-px bg-border", className)} {...p} />;
