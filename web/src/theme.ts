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

/** The page behind the cards -- NOT the same colour as `surface()`.
 *
 * The shell used to paint the body and every `Card` from `surface()` alike,
 * which left a card detectable only by its 1px border: the whole page read as
 * one flat sheet. See italy_dashboard/palette.py's PAGE_BG_* for why the card
 * is the lighter of the pair in both modes.
 */
export function pageBg(): string {
  return palette.page_bg[currentMode()];
}

/** Card/control/table edges. Distinct from `gridline()`, which is the fainter
 * inside-the-chart line -- previously both roles shared one token, so a card
 * edge was drawn no more strongly than a gridline. */
export function border(): string {
  return palette.border[currentMode()];
}

/** Axis lines and tick labels: chrome, deliberately dimmer than any ink used
 * for copy, but still over WCAG's 3:1 non-text floor. Observable Plot's own
 * default is `currentColor` at full strength (i.e. `inkPrimary()`), which is
 * why an untreated chart shouts its tick labels as loudly as its title -- see
 * charts/plotTheme.ts, which feeds this into every spec.
 */
export function axis(): string {
  return palette.axis[currentMode()];
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

/** The amber accent for `Callout` (ui.tsx): a data-quality caveat about data
 * that IS being shown, distinct in hue from `series(2)`'s categorical orange
 * so a warning box is never mistaken for a chart series. See
 * italy_dashboard/palette.py's WARNING_LIGHT/WARNING_DARK for how the values
 * were chosen (contrast-checked against `surface()`, not eyeballed). */
export function warning(): string {
  return palette.warning[currentMode()];
}
