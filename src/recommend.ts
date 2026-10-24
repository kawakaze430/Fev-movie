import type { Movie } from './catalog';

const genres = (movie: Movie): Set<string> => new Set(movie.genres.map(g => g.toLocaleLowerCase()));
const tokens = (movie: Movie): Set<string> => new Set(
  (movie.title + ' ' + movie.synopsis).toLocaleLowerCase().match(/[a-z0-9]{3,}/g) || [],
);

/** Offline fallback: transparent metadata similarity, no third-party calls or tracking. */
export function recommendLocal(movies: Movie[], savedIds: string[], limit = 6): Movie[] {
  const liked = movies.filter(movie => savedIds.includes(movie.id));
  const ignored = new Set(savedIds);
  const genreCounts = new Map<string, number>();
  const interestingWords = new Set<string>();
  liked.forEach(movie => {
    genres(movie).forEach(g => genreCounts.set(g, (genreCounts.get(g) || 0) + 1));
    tokens(movie).forEach(w => interestingWords.add(w));
  });
  const scored = movies.filter(movie => !ignored.has(movie.id)).map(movie => {
    const overlap = [...genres(movie)].reduce((n, g) => n + (genreCounts.get(g) || 0), 0);
    const words = [...tokens(movie)].filter(w => interestingWords.has(w)).length;
    const nearestYear = liked.reduce((n, m) => m.year != null && movie.year != null ? Math.min(n, Math.abs(m.year - movie.year)) : n, 100);
    const score = liked.length ? 5 * overlap + words * .25 + Math.max(0, 8 - nearestYear) / 8 : (movie.year || 0) / 1000;
    return { movie, score };
  }).sort((a, b) => b.score - a.score || a.movie.title.localeCompare(b.movie.title));
  const result: Movie[] = [];
  const used = new Map<string, number>();
  while (scored.length && result.length < Math.min(Math.max(0, limit), 24)) {
    let best = 0, bestScore = -Infinity;
    scored.forEach(({ movie, score }, i) => {
      const diversity = [...genres(movie)].reduce((n, g) => n + (used.get(g) || 0), 0) * .45;
      if (score - diversity > bestScore) { bestScore = score - diversity; best = i; }
    });
    const [{ movie }] = scored.splice(best, 1);
    result.push(movie);
    genres(movie).forEach(g => used.set(g, (used.get(g) || 0) + 1));
  }
  return result;
}
