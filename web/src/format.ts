// Number-formatting helpers that mirror Python's str.format mini-language
// exactly. JavaScript has no equivalent format spec, and the obvious
// locale-aware call in an Italian-language app -- `n.toLocaleString("it-IT")`
// -- swaps the separators (584.514 instead of Python's 584,514): a different
// string, not a rendering detail. These match Python's formatting, not the
// browser's locale, because the conformance matrix pins Python's exact
// output. Shared across query files instead of each carrying its own copy
// (italy_dashboard.queries has no equivalent helper either -- it relies on
// f-string format specs directly -- so there is nothing to mirror 1:1 here
// beyond the two spec forms this app's queries actually use).

/** `n:+.Nf` the way Python's str.format does: a `-` for any negative value
 * (including one that rounds to zero, e.g. -0.001 at 2 decimals -> "-0.00")
 * and a `+` otherwise. */
export function signedFixed(n: number, decimals: number): string {
  const negative = n < 0 || Object.is(n, -0);
  const fixed = Math.abs(n).toFixed(decimals);
  return negative ? `-${fixed}` : `+${fixed}`;
}

/** `n:,.Nf` the way Python's str.format does: a comma thousands separator on
 * the integer part, exactly `decimals` digits after a literal `.`, and a
 * leading `-` for negative values -- regardless of locale. */
export function commaFixed(n: number, decimals: number): string {
  const negative = n < 0 || Object.is(n, -0);
  const fixed = Math.abs(n).toFixed(decimals);
  const [intPart, decPart] = fixed.split(".");
  const grouped = intPart!.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const out = decPart !== undefined ? `${grouped}.${decPart}` : grouped;
  return negative ? `-${out}` : out;
}
