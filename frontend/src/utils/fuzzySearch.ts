/** Levenshtein edit distance, capped early once it exceeds `max` (we only
 * ever care about "close enough", not the exact distance). */
function editDistanceWithin(a: string, b: string, max: number): boolean {
  if (Math.abs(a.length - b.length) > max) return false;
  const dp: number[] = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prevDiag = dp[0];
    dp[0] = i;
    let rowMin = dp[0];
    for (let j = 1; j <= b.length; j++) {
      const temp = dp[j];
      dp[j] = a[i - 1] === b[j - 1]
        ? prevDiag
        : 1 + Math.min(prevDiag, dp[j], dp[j - 1]);
      prevDiag = temp;
      rowMin = Math.min(rowMin, dp[j]);
    }
    if (rowMin > max) return false; // whole row exceeded - no cell can recover
  }
  return dp[b.length] <= max;
}

/** Phase 4.4: "typing 'run' returns zero results" - matches whole words
 * with light typo tolerance (edit distance 1 for words of 4+ characters)
 * instead of requiring an exact substring, without pulling in an
 * embedding model for what's fundamentally a short admin-facing list. */
export function fuzzyMatches(haystack: string, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const hay = haystack.toLowerCase();
  if (hay.includes(needle)) return true;

  const hayWords = hay.split(/\s+/).filter(Boolean);
  return needle.split(/\s+/).filter(Boolean).every((word) => {
    if (hay.includes(word)) return true;
    if (word.length < 4) return false; // too short for typo tolerance to mean anything
    const maxDistance = word.length >= 7 ? 2 : 1;
    return hayWords.some((hw) => editDistanceWithin(word, hw, maxDistance));
  });
}
