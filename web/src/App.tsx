import { useEffect, useState } from "react";
import { currentMode, gridline, inkPrimary, surface, type Mode } from "./theme";

type Choice = Mode | "system";

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

  // Re-paint if the OS preference changes while "system" is selected -- the
  // toggle below handles the explicit-choice case itself, on click.
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystemChange = () => {
      if (readStoredChoice() === "system") paintShell();
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
  }

  return (
    <main style={{ padding: "1.5rem" }}>
      <h1 style={{ color: inkPrimary() }}>Italy Dashboard</h1>
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
        Colour mode: {choice} (currently {currentMode()})
      </button>
    </main>
  );
}
