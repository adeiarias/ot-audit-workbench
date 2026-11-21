import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "–";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);  // el backend guarda UTC sin zona
  return withTime ? d.toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }) : d.toLocaleDateString("es-ES");
}
