import { useEffect, useState } from "react";

/** One entry in the site nav: the hash slug and its display label.
 *
 * `italy_dashboard/components.py`'s `NAV_LINKS` is the reference for which
 * pages exist and in what order -- home, crime, population, education,
 * climate, climate-crime, labor, economy. Slugs drop the leading slash Reflex's
 * `href`s carry (`/climate-crime` -> `climate-crime`): this app builds its
 * own hash href as `#/${slug}` (see App.tsx), so the slug alone is the
 * single source of truth for both the href and the route match.
 */
export interface RouteDef {
  readonly slug: string;
  readonly label: string;
}

export const ROUTES: readonly RouteDef[] = [
  { slug: "home", label: "Home" },
  { slug: "crime", label: "Crime" },
  { slug: "population", label: "Population" },
  { slug: "education", label: "Education" },
  { slug: "climate", label: "Climate" },
  { slug: "climate-crime", label: "Climate × Crime" }, // noqa: RUF001 -- matches nav_climate_crime
  { slug: "labor", label: "Labor" },
  { slug: "economy", label: "Economy" },
] as const;

const DEFAULT_SLUG = "home";

/** Hash routing (`#/crime`), deliberately NOT real paths with a server-side
 * SPA rewrite rule (e.g. Netlify's `[[redirects]] from="/*" to="/index.html"`,
 * a mechanism GitHub Pages does not even have). That catch-all would
 * also intercept the request for `mart_climate_daily.parquet`, which is
 * deliberately absent from this build: `registerParquetViews` (db.ts) relies
 * on that request genuinely 404ing to record the dataset as unavailable --
 * with a catch-all it would get `200 OK` and an HTML document instead,
 * turning a handled absence into a DuckDB parse error. Hash routing needs no
 * server config at all, so there is no rewrite rule to ever misconfigure.
 *
 * An empty or bare `#`/`#/` hash (fresh load, or a link back to `#/`) means
 * "home" -- but an unrecognised slug is returned VERBATIM, not coerced to
 * "home": that distinction is what lets a dangling nav link (one whose slug
 * matches no page) be told apart from a genuine fresh load, instead of both
 * silently landing on the home page.
 */
function parseHash(hash: string): string {
  const slug = hash.replace(/^#\/?/, "");
  return slug === "" ? DEFAULT_SLUG : slug;
}

/** The active route slug, parsed from `location.hash` and kept in sync with
 * it via the `hashchange` event -- the entire routing mechanism for this app. */
export function useRoute(): string {
  const [route, setRoute] = useState<string>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return route;
}
