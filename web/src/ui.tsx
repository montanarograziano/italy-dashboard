import type { ReactNode, SelectHTMLAttributes } from "react";
import { gridline, inkMuted, inkPrimary, surface, warning } from "./theme";

// Shared page-shell components, pulled out of six near-identical copies
// (Crime.tsx, Economy.tsx, ClimateCrime.tsx, Climate.tsx, Labor.tsx,
// Population.tsx each independently defined their own `Card`/`EmptyNote`,
// and Climate.tsx its own `SectionHeading`) plus two components new to this
// module (`Callout`, `Select`) that fix the two static-app-only visual
// regressions this task exists for: an unstyled native `<select>` and a
// data-quality caveat rendered through the same plain component as "no data"
// filler text. `Loading` is NOT consolidated here even though it is also
// duplicated -- its Climate.tsx version takes a `stage` prop the other five
// don't need, and nothing asked for it, so it stays out of scope.

export function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h2 style={{ color: inkPrimary(), fontSize: "1.25rem", margin: "1.75rem 0 0.5rem" }}>{children}</h2>
  );
}

// `subtitle` is typed `ReactNode | undefined` here, even though five of the
// six duplicated copies (Crime/ClimateCrime/Economy/Labor/Population) required
// a plain `string`: Climate.tsx's copy is the strict superset (an optional,
// richer subtitle -- e.g. `undefined` for a card with nothing to say yet, or
// a `<>...</>` fragment), so consolidating on it changes nothing at any of
// the other five call sites, which all already pass a plain string.
export function Card({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      style={{
        background: surface(),
        border: `1px solid ${gridline()}`,
        borderRadius: "10px",
        padding: "1.25rem",
        marginBottom: "1rem",
      }}
    >
      <h3 style={{ color: inkPrimary(), margin: "0 0 0.25rem", fontSize: "1.05rem" }}>{title}</h3>
      {subtitle ? (
        <p style={{ color: inkMuted(), fontSize: "0.85em", margin: "0 0 0.75rem" }}>{subtitle}</p>
      ) : null}
      {children}
    </section>
  );
}

/** A plain-words placeholder for "there is nothing to draw here, and here is
 * why" -- distinct from a chart rendered with zero marks, which looks like a
 * bug rather than an honest answer. Also distinct from `Callout` below: this
 * is for a genuine ABSENCE (no rows for this selection, a mart not built
 * yet, a table excluded from this build) -- never for a caveat about data
 * that IS being shown. Deliberately unstyled/non-alerting: nothing failed,
 * so it does not need to announce itself the way a warning does.
 */
export function EmptyNote({ children }: { children: ReactNode }) {
  return <p style={{ color: inkMuted(), fontStyle: "italic", margin: 0 }}>{children}</p>;
}

/**
 * A data-quality/interpretive caveat about data that IS being shown -- "this
 * national aggregate is a northern-weighted average", "this correlation is
 * confounded" -- as opposed to `EmptyNote`'s "there is nothing here at all".
 *
 * Before this component existed, the static app rendered every one of these
 * caveats through a plain bordered `<div>`/`<p>` with no colour and no icon,
 * indistinguishable from a neutral message -- Reflex's equivalent is
 * `rx.callout(..., color_scheme="amber", icon="triangle_alert")`
 * (climate.py's climate_coverage_note, climate_crime.py's cc_coverage_note).
 *
 * One severity tier only, deliberately: Reflex actually varies color_scheme
 * per message (amber for a coverage caveat, gray+icon="info" for
 * climate_crime.py's cc_caveat, blue for crime.py's income_missing, orange
 * for a missing mart) -- reproducing that whole taxonomy was not asked for
 * here, and a single "important, notice this" tone covers every place this
 * component is actually used. Genuine absence states (mart not built, no
 * rows for this selection, a table excluded from this build) stay on
 * `EmptyNote`, matching Reflex's OWN plain-`rx.text` treatment of this app's
 * two other real caveats (crime.py's method_note and income_caveat are
 * `rx.text`, not `rx.callout`, in the Reflex reference too -- see the six
 * page files' comments on exactly which caveat went which way and why).
 */
export function Callout({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div
      role="note"
      data-testid={testId}
      style={{
        display: "flex",
        gap: "0.65rem",
        alignItems: "flex-start",
        background: `color-mix(in srgb, ${warning()} 14%, ${surface()})`,
        border: `1px solid ${warning()}`,
        borderRadius: "8px",
        padding: "0.8rem 1rem",
        color: inkPrimary(),
        fontSize: "0.9em",
      }}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        width="1.15em"
        height="1.15em"
        fill="none"
        stroke={warning()}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ flex: "none", marginTop: "0.15em" }}
      >
        <path d="M12 2 22 20 2 20Z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="16.5" x2="12" y2="16.6" />
      </svg>
      <div style={{ minWidth: 0 }}>{children}</div>
    </div>
  );
}

/**
 * A native `<select>`, restyled: `appearance: none` (in the `.select` class,
 * theme.css) drops the OS chrome that made every dropdown a plain white box
 * regardless of dark mode, replaced with a border/background/focus ring all
 * driven by theme.ts. Native semantics are kept on purpose -- keyboard nav,
 * typeahead, screen readers -- nothing here builds a custom listbox.
 *
 * Colour split the same way `.spinner` (theme.css) splits it: the STATIC
 * background/border are plain values set inline below (surface()/gridline(),
 * same tokens `Card` uses for its own border), because an inline `style`
 * attribute always wins over a stylesheet rule and would silently defeat any
 * CSS `:focus-visible` override of the same property. The FOCUS RING instead
 * reads `currentColor` in theme.css, with the actual colour supplied by the
 * one inline `color` set on the wrapping `<span>` -- exactly how `.spinner`
 * is used inside a parent with its own inline `color`.
 *
 * `SelectHTMLAttributes<HTMLSelectElement>` is spread straight onto the
 * underlying element, so every existing call site's `value`/`onChange`/
 * `disabled`/`data-testid`/children (`<option>`s) keeps working unchanged.
 */
export function Select({ style, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className="select-wrap" style={{ color: inkPrimary() }}>
      <select className="select" style={{ background: surface(), borderColor: gridline(), ...style }} {...props} />
    </span>
  );
}
