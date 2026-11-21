import { Monitor, Moon, Palette, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { PRESETS, useTheme, type Mode, type Preset } from "@/lib/theme";

export function ThemeMenu() {
  const { mode, preset, isDark, setMode, setPreset } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Apariencia">{isDark ? <Moon /> : <Sun />}</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Modo</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={mode} onValueChange={(v) => setMode(v as Mode)}>
          <DropdownMenuRadioItem value="light"><Sun /> Claro</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark"><Moon /> Oscuro</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system"><Monitor /> Sistema</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="flex items-center gap-1.5"><Palette className="size-3.5" /> Tema</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={preset} onValueChange={(v) => setPreset(v as Preset)}>
          {PRESETS.map((p) => (
            <DropdownMenuRadioItem key={p.value} value={p.value}>
              <span className="flex gap-0.5">{p.swatch.map((c) => <span key={c} className="size-3 rounded-full border" style={{ background: c }} />)}</span>
              {p.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

