import { useEffect, useState, type ReactNode } from "react";
import Climate from "./pages/Climate";
import Crime from "./pages/Crime";
import Economy from "./pages/Economy";
import Home from "./pages/Home";
import Labor from "./pages/Labor";
import Population from "./pages/Population";
import { ROUTES, useRoute } from "./router";
import { currentMode, gridline, inkMuted, inkPrimary, inkSecondary, surface, type Mode } from "./theme";

type Choice = Mode | "system";

/** Placeholder for a nav-registered page this plan hasn't built yet
 * (climate-crime -- see the plan's progress ledger: Task 1 built the
 * router, nav and home page, Task 2 added economy, labor and population,
 * Task 3 added crime).
 * Every ROUTES entry must resolve to something with an `<h1>` so the nav
 * link test (`test_every_nav_link_reaches_a_page_that_renders`) can tell
 * "not built yet" apart from "genuinely broken link" -- an UNREGISTERED
 * slug (matching no ROUTES entry at all) still renders nothing, which is
 * what lets that same test catch a dangling link once one exists.
 */
function ComingSoon({ label }: { label: string }) {
  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 0.35rem" }}>{label}</h1>
      <p style={{ color: inkMuted() }}>This page hasn&apos;t been built yet.</p>
    </div>
  );
}

const STORAGE_KEY = "italy-dashboard-color-mode";

function readStoredChoice(): Choice {
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return raw === "light" || raw === "dark" ? raw : "system";
}

function applyChoice(choice: Choice): void {
  if (choice === "system") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = choice;
  }
}

/** Paint the shell from the palette for whichever mode is active right now.
 *
 * Called synchronously at module load (below) rather than from a React
 * effect: a `useEffect` version would not run until after the first paint,
 * which is late enough for a test asserting on the FIRST computed style
 * (`test_static_app.py`) to see the browser's default white before the
 * effect ever fires. Called again on every mode change for the same reason
 * -- see `cycle()` and the system-preference listener below.
 */
function paintShell(): void {
  document.body.style.backgroundColor = surface();
  document.body.style.color = inkPrimary();
}

// Restore whatever the visitor chose last time (or "system") and paint
// immediately, before React has even mounted: the shell must never render
// with the browser's default background and repaint a moment later.
applyChoice(readStoredChoice());
paintShell();

export default function App() {
  const [choice, setChoice] = useState<Choice>(readStoredChoice);
  // The RESOLVED mode ("system" collapsed to whatever it means right now),
  // lifted into state so it can be a dependency of downstream `useMemo`s.
  // theme.ts's accessors (series/gridline/inkPrimary/divergingSteps) are read
  // at Plot SPEC-BUILD time, and Climate.tsx's chart specs are memoised on
  // data only -- a mode change touches neither the data nor (by itself) any
  // state Climate.tsx owns, so without this the chart DOM is never rebuilt
  // and every Plot-baked colour is stuck on whichever mode was active on
  // first render. Only colour paths driven live by CSS (the body background,
  // the stripes' `var(--div-N)` cell fill) were ever exempt from that bug.
  const [mode, setMode] = useState<Mode>(currentMode);

  // Re-paint if the OS preference changes while "system" is selected -- the
  // toggle below handles the explicit-choice case itself, on click.
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystemChange = () => {
      if (readStoredChoice() === "system") {
        paintShell();
        setMode(currentMode());
      }
    };
    media.addEventListener("change", onSystemChange);
    return () => media.removeEventListener("change", onSystemChange);
  }, []);

  function cycle(): void {
    const next: Choice = choice === "system" ? "light" : choice === "light" ? "dark" : "system";
    if (next === "system") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, next);
    }
    applyChoice(next);
    paintShell();
    setChoice(next);
    setMode(currentMode());
  }

  // Route switch: the entire nav must be additive from here on -- every
  // later task in this plan only ADDS a `case` (or replaces a `ComingSoon`
  // with a real import), never touches `useRoute`/`ROUTES` themselves (see
  // router.tsx's docstring and the plan's pre-flight scan). An unregistered
  // slug (in neither this switch nor ROUTES) renders nothing, on purpose --
  // see `ComingSoon`'s docstring above for why that is load-bearing for the
  // nav-link test, not an oversight.
  const route = useRoute();
  const routeDef = ROUTES.find((r) => r.slug === route);
  let page: ReactNode;
  switch (route) {
    case "home":
      page = <Home />;
      break;
    case "climate":
      page = <Climate mode={mode} />;
      break;
    case "crime":
      page = <Crime mode={mode} />;
      break;
    case "economy":
      page = <Economy mode={mode} />;
      break;
    case "labor":
      page = <Labor mode={mode} />;
      break;
    case "population":
      page = <Population mode={mode} />;
      break;
    default:
      page = routeDef ? <ComingSoon label={routeDef.label} /> : null;
  }

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto", padding: "1.5rem" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <span style={{ color: inkPrimary(), fontSize: "1.25em", fontWeight: 700 }}>
          Italy Dashboard
        </span>
        <button
          type="button"
          onClick={cycle}
          style={{
            color: inkPrimary(),
            border: `1px solid ${gridline()}`,
            background: "transparent",
            borderRadius: "4px",
            padding: "0.4rem 0.8rem",
            cursor: "pointer",
          }}
        >
          Colour mode: {choice} (currently {mode})
        </button>
      </div>
      <nav
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "1.25rem",
          margin: "1rem 0 1.5rem",
          paddingBottom: "0.75rem",
          borderBottom: `1px solid ${gridline()}`,
        }}
      >
        {ROUTES.map((r) => {
          const active = r.slug === route;
          return (
            <a
              key={r.slug}
              href={`#/${r.slug}`}
              aria-current={active ? "page" : undefined}
              style={{
                color: active ? inkPrimary() : inkSecondary(),
                fontWeight: active ? 700 : 400,
                fontSize: "0.95em",
                textDecoration: "none",
              }}
            >
              {r.label}
            </a>
          );
        })}
      </nav>
      <main>{page}</main>
    </div>
  );
}
