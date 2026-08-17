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

/** Round-half-to-even at `decimals` places, the way Python's `round()` --
 * and therefore `str.format`'s fixed-point specs (`:.Nf`, `:,.Nf`, `:+.Nf`),
 * which use the same rounding -- round. `Number.prototype.toFixed` rounds
 * half away from zero instead, which disagrees exactly at an `x.5` boundary
 * at the target precision: `(58.25).toFixed(1)` is `"58.3"`, but Python's
 * `f"{58.25:.1f}"` is `"58.2"`. Every formatter below, and every bare
 * `.toFixed()` call site in the query layer, must round through this first
 * -- `.toFixed()` alone is only safe as the final *layout* step on an
 * already-rounded value.
 *
 * This does NOT scale `n` by `10 ** decimals` and compare the floating-point
 * result to `x.5` with a tolerance -- an earlier version of this function did,
 * and it is wrong, not just imprecise. `mart_crime_climate`'s own
 * `raw_slope` is `0.2805`, whose nearest double is actually
 * `0.28050000000000002709...`: genuinely, if narrowly, ABOVE the true
 * midpoint, so Python correctly rounds it up to `0.281` with no tie to
 * break. But `0.2805 * 1000` computed in floating point rounds (as its OWN
 * separate operation) to exactly `280.5`, because 280.5 happens to be
 * exactly representable and closer to the true product than any other
 * double -- so a scale-then-compare approach sees a tie that reality does
 * not have, and resolves it to the wrong side (round-to-even gives `280`,
 * i.e. `"0.280"`; measured, via this app's own crime_climate_stats
 * conformance case, as a real divergence, not a hypothetical one). No
 * tolerance threshold fixes this: the excess this loses (~2.7e-14) and the
 * tolerance a genuine tie needs to survive floating-point noise are not
 * reliably distinguishable at every magnitude and decimal count this
 * function is asked to handle.
 *
 * Decomposing `n`'s IEEE754 bit pattern into its exact `mantissa * 2^exponent`
 * form and doing the scaling and rounding in BigInt integer arithmetic
 * avoids an intermediate floating-point operation entirely, so there is
 * nothing left to be imprecise about: a tie is only ever a tie when it
 * truly, exactly is one. Generalises the integer-only bankersRound that
 * climate.ts's `divergingBucket` used to carry its own copy of (decimals =
 * 0), so there is one rounding implementation in the app, not two.
 */
export function pythonRound(n: number, decimals: number): number {
  if (!Number.isFinite(n) || n === 0) return n;
  const sign = n < 0 ? -1 : 1;

  // Decompose |n|'s IEEE754 binary64 bit pattern into mantissa * 2 ** exp,
  // exactly -- no arithmetic on `n` itself yet, so no rounding has happened.
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, Math.abs(n));
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  let exp = (hi >>> 20) & 0x7ff;
  let mantissa = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  if (exp === 0) {
    exp = -1074; // subnormal: no implicit leading bit
  } else {
    mantissa |= 1n << 52n; // implicit leading 1
    exp -= 1075; // unbias (1023) and account for the 52 mantissa bits
  }

  // |n| * 10 ** decimals == scaledMantissa * 2 ** scaledExp, still exactly:
  // 10 ** decimals == 2 ** decimals * 5 ** decimals, and the 5 ** decimals
  // factor folds into the (integer) mantissa while the 2 ** decimals factor
  // folds into the (integer) exponent.
  const scaledMantissa = mantissa * 5n ** BigInt(decimals);
  const scaledExp = exp + decimals;

  let result: bigint;
  if (scaledExp >= 0) {
    result = scaledMantissa << BigInt(scaledExp); // already an exact integer
  } else {
    const k = BigInt(-scaledExp);
    const whole = scaledMantissa >> k; // floor, exact (BigInt shift truncates toward zero on a non-negative value)
    const remainder = scaledMantissa - (whole << k); // exact fractional numerator over 2 ** k
    const half = 1n << (k - 1n);
    if (remainder < half) result = whole;
    else if (remainder > half) result = whole + 1n;
    else result = whole % 2n === 0n ? whole : whole + 1n; // a genuine, exact tie: to even
  }

  return (sign * Number(result)) / 10 ** decimals;
}

/** `n:+.Nf` the way Python's str.format does: a `-` for any negative value
 * (including one that rounds to zero, e.g. -0.001 at 2 decimals -> "-0.00")
 * and a `+` otherwise. */
export function signedFixed(n: number, decimals: number): string {
  const negative = n < 0 || Object.is(n, -0);
  const fixed = pythonRound(Math.abs(n), decimals).toFixed(decimals);
  return negative ? `-${fixed}` : `+${fixed}`;
}

/** `n:,.Nf` the way Python's str.format does: a comma thousands separator on
 * the integer part, exactly `decimals` digits after a literal `.`, and a
 * leading `-` for negative values -- regardless of locale. */
export function commaFixed(n: number, decimals: number): string {
  const negative = n < 0 || Object.is(n, -0);
  const fixed = pythonRound(Math.abs(n), decimals).toFixed(decimals);
  const [intPart, decPart] = fixed.split(".");
  const grouped = intPart!.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const out = decPart !== undefined ? `${grouped}.${decPart}` : grouped;
  return negative ? `-${out}` : out;
}
