import { tr, trt, useLang } from "../i18n";
import { inkPrimary, inkSecondary } from "../theme";

/** Branded "page not found" content for a genuinely unregistered hash route.
 *
 * Mirrors italy_dashboard/pages/not_found.py -- the same header/nav shell
 * (App.tsx renders this inside `<main>`, under the always-present nav), a
 * heading, a short explanation, and a link back home. Before this existed,
 * an unmatched slug rendered `null` here: header, nav and colour-mode
 * control all painted fine, but the content area was silently empty, with
 * no error, no message, nothing to tell a visitor (or a dangling nav link)
 * apart from a genuinely broken page.
 *
 * Only ever rendered for a slug that is NOT in `ROUTES` (see App.tsx's
 * `default` switch branch): a slug that IS in `ROUTES` still renders `null`
 * on a missing `case`, on purpose -- that is what lets
 * `test_every_nav_link_reaches_a_page_that_renders` (web/../tests) catch a
 * deleted page's `case` at all. A generic "not found" `<h1>` on THAT branch
 * too would satisfy the same "some h1 has text" check and mask exactly the
 * regression that test exists to catch.
 */
export default function NotFound({ slug }: { slug: string }) {
  useLang();
  return (
    <div>
      <h1 style={{ color: inkPrimary(), margin: "0 0 0.35rem" }}>{tr("Page not found")}</h1>
      <p style={{ color: inkSecondary(), margin: "0 0 1.5rem" }}>
        {trt("There is no page at “#/{slug}”. Use the navigation above, or go back home.", { slug })}
      </p>
      <a href="#/" style={{ color: inkPrimary(), fontWeight: 600 }}>
        {tr("Back to home")}
      </a>
    </div>
  );
}
