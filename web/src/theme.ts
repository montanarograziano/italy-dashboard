import palette from "../../shared/palette.json";

export type Mode = "light" | "dark";

/** The mode the page is actually rendering in.
 *
 * Three states, matching how the artifact viewer and the Reflex app both
 * behave: an explicit choice sets `data-theme` on <html>, and the default
 * "system" setting sets nothing, leaving `prefers-color-scheme` to decide.
 */
export function currentMode(): Mode {
  const explicit = document.documentElement.dataset.theme;
  if (explicit === "light" || explicit === "dark") return explicit;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** The nth categorical colour (wrapping), for the current mode. */
export function series(n: number): string {
  const scale = palette.categorical[currentMode()];
  return scale[n % scale.length]!;
}

/** The seven-step diverging ramp, cool -> neutral -> warm, for the current mode. */
export function divergingSteps(): string[] {
  return palette.diverging[currentMode()];
}

/** The five-step sequential ramp, pale -> deep, for the current mode. */
export function sequentialSteps(): string[] {
  return palette.sequential[currentMode()];
}

// The remaining accessors mirror italy_dashboard/theme.py's surface(),
// ink_primary(), ink_secondary(), ink_muted() and gridline() in camelCase, so
// the two frontends reach for the same named set of UI tokens. Their values
// live in italy_dashboard/palette.py (not just theme.py) and are projected
// into shared/palette.json by scripts/generate_palette.py, same as the chart
// scales above -- see that script's docstring for why regeneration is
// mandatory rather than optional.

export function surface(): string {
  return palette.surface[currentMode()];
}

export function inkPrimary(): string {
  return palette.ink_primary[currentMode()];
}

export function inkSecondary(): string {
  return palette.ink_secondary[currentMode()];
}

export function inkMuted(): string {
  return palette.ink_muted[currentMode()];
}

export function gridline(): string {
  return palette.gridline[currentMode()];
}
