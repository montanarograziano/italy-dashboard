import type { ReactNode, SelectHTMLAttributes } from "react";
import { border, inkMuted, inkPrimary, inkSecondary, surface, warning } from "./theme";

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
  // A small-caps "eyebrow", not another large heading. A page has three levels
  // of title (its `<h1>`, this, and each Card's `<h3>`), and all three used to
  // be large and bold at near-identical sizes, so the hierarchy read as noise.
  // Making the MIDDLE level the smallest and most letterspaced separates it by
  // KIND rather than by degree: it reads as a divider label, which is what it
  // is, and stops competing with the card titles underneath it.
  return (
    <h2
      style={{
        color: inkPrimary(),
        fontSize: "0.8rem",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.07em",
        margin: "2.25rem 0 0.75rem",
      }}
    >
      {children}
    </h2>
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
        // `surface()` on a page painted `pageBg()` (App.tsx): two different
        // colours now. They used to be the same one, so a card was detectable
        // only by its hairline and the page read as a single flat sheet. See
        // italy_dashboard/palette.py's PAGE_BG_*.
        background: surface(),
        // `border()`, not `gridline()`: one token was doing both jobs, so a
        // card's outer edge was drawn no more strongly than a gridline inside
        // a chart. Separate roles now.
        border: `1px solid ${border()}`,
        borderRadius: "10px",
        padding: "1.25rem 1.35rem 1.4rem",
        marginBottom: "1rem",
        // The second half of the elevation cue. The surface/page contrast is
        // deliberately sub-perceptual (1.11:1) because anything stronger reads
        // as a coloured panel rather than a lifted one, so the shadow is what
        // actually resolves the card as an object: a tight dark line for the
        // edge, a wide diffuse one for the lift.
        boxShadow: "0 1px 2px rgba(0,0,0,0.04), 0 4px 12px -2px rgba(0,0,0,0.06)",
      }}
    >
      <h3
        style={{
          color: inkPrimary(),
          margin: "0 0 0.15rem",
          fontSize: "1rem",
          fontWeight: 650,
          letterSpacing: "-0.005em",
        }}
      >
        {title}
      </h3>
      {subtitle ? (
        // `inkSecondary()`, not `inkMuted()`: a card's subtitle is the sentence
        // stating what the chart measures -- often the only place the unit or
        // baseline appears -- so it is content, not a footnote. `inkMuted()` is
        // the weakest ink in the palette (4.9:1, at the AA floor) and pushed
        // exactly the text a reader needs most to the faintest thing on the
        // card. `EmptyNote` below keeps `inkMuted()`; it genuinely is an aside.
        <p
          style={{
            color: inkSecondary(),
            fontSize: "0.86em",
            lineHeight: 1.45,
            margin: "0 0 1rem",
            maxWidth: "68ch",
          }}
        >
          {subtitle}
        </p>
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
        background: `color-mix(in srgb, ${warning()} 12%, ${surface()})`,
        // A left accent rule rather than a full amber box. A saturated border
        // all the way round an already amber-tinted panel is two competing
        // edges on one message, and at this page's width it drew a heavy
        // rectangle that outweighed the charts it was commenting on. One accent
        // edge keeps the "notice this" signal and lets the shape stay quiet.
        border: `1px solid color-mix(in srgb, ${warning()} 30%, ${surface()})`,
        borderLeft: `3px solid ${warning()}`,
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
      <select className="select" style={{ background: surface(), borderColor: border(), ...style }} {...props} />
    </span>
  );
}
