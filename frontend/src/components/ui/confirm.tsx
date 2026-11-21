import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "./button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./dialog";

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Confirmar", destructive, onConfirm }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description: string; confirmLabel?: string; destructive?: boolean; onConfirm: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button variant={destructive ? "destructive" : "default"} disabled={busy} onClick={async () => { setBusy(true); try { await onConfirm(); onOpenChange(false); } finally { setBusy(false); } }}>
            {busy && <Loader2 className="animate-spin" />} {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
