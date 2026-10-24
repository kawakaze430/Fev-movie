export type MovieLink = { label: string; quality: string | null; url: string; size: string | null };
export type Movie = {
  id: string; title: string; year: number | null; genres: string[]; synopsis: string; poster: string | null;
  links: MovieLink[]; sources: { channelId: string; channelName: string; messageId: string }[];
  rights: { distribution: 'cleared'; poster: 'original' | 'licensed' | 'none'; evidence: string };
};
export type Catalog = { schemaVersion: 1; generatedAt: string; kind: 'demo' | 'public'; movies: Movie[] };

// Match the importer’s publication policy before exposing any external destination.
// URL canonicalization also normalizes legacy compact, octal and hex IPv4 forms.
export function safeUrl(value: string): boolean {
  if (!/^https?:\/\//i.test(value) || value.length > 8192 || /[\s\u0000-\u0020\u007f\\]/u.test(value)) return false;
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || (url.port && !['80', '443'].includes(url.port))) return false;
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    // IPv6 literal destinations are not supported by the importer’s public-host policy.
    if (!host.includes('.') || /[\[\]:]/.test(host) || host === 'localhost' || host === 'metadata.google.internal' || /\.(?:localhost|local|internal|test|invalid)$/.test(host)) return false;
    if (/^\d+(?:\.\d+){3}$/.test(host)) {
      const [a, b, c] = host.split('.').map(Number);
      if (a === 0 || a === 10 || a === 127 || a >= 224 || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 168 || (b === 0 && (c === 0 || c === 2)))) || (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100))) || (a === 203 && b === 0 && c === 113)) return false;
      return true;
    }
    return host.length <= 253 && host.split('.').every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label));
  } catch { return false; }
}
function exactKeys(value: unknown, keys: string[]): boolean {
  return !!value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
function string(value: unknown): value is string { return typeof value === 'string'; }
function safePoster(value: unknown): boolean {
  return value === null || (string(value) && /^\/(?!\/)(?:art|posters)\/[a-zA-Z0-9_./-]+\.(?:svg|png|jpe?g|webp)$/i.test(value) && !value.split('/').includes('..'));
}
export function parseCatalog(value: unknown): Catalog {
  if (!exactKeys(value, ['schemaVersion', 'generatedAt', 'kind', 'movies'])) throw new Error('The catalog file is not an object.');
  const data = value as Record<string, unknown>;
  if (data.schemaVersion !== 1 || !['demo', 'public'].includes(String(data.kind)) || !string(data.generatedAt) || Number.isNaN(Date.parse(data.generatedAt)) || !Array.isArray(data.movies)) throw new Error('The catalog has an unsupported format.');
  const ids = new Set<string>();
  for (const record of data.movies) {
    if (!exactKeys(record, ['id', 'title', 'year', 'genres', 'synopsis', 'poster', 'links', 'sources', 'rights'])) throw new Error('A film record is invalid.');
    const m = record as Movie;
    if (!string(m.id) || !m.id || ids.has(m.id) || !string(m.title) || !m.title.trim() || !(m.year === null || (Number.isInteger(m.year) && m.year >= 1888 && m.year <= 2200)) || !Array.isArray(m.genres) || !m.genres.every(string) || !string(m.synopsis) || !safePoster(m.poster) || !Array.isArray(m.links) || !Array.isArray(m.sources)) throw new Error('A film record is incomplete or duplicated.');
    if (!exactKeys(m.rights, ['distribution', 'poster', 'evidence']) || m.rights.distribution !== 'cleared' || !['original', 'licensed', 'none'].includes(m.rights.poster) || !string(m.rights.evidence) || !m.rights.evidence.trim() || (m.poster && m.rights.poster === 'none')) throw new Error('A film is missing distribution or artwork clearance.');
    if (data.kind === 'public' && m.poster?.endsWith('.svg')) throw new Error('Published imported artwork must be a validated raster asset.');
    for (const link of m.links) if (!exactKeys(link, ['label', 'quality', 'url', 'size']) || !string(link.label) || !string(link.url) || !safeUrl(link.url) || !(link.quality === null || string(link.quality)) || !(link.size === null || string(link.size))) throw new Error('A film contains an invalid external link.');
    for (const source of m.sources) if (!exactKeys(source, ['channelId', 'channelName', 'messageId']) || !string(source.channelId) || !string(source.channelName) || !string(source.messageId)) throw new Error('A film source is incomplete.');
    ids.add(m.id);
  }
  return data as unknown as Catalog;
}
export const assetUrl = (path: string): string => `${import.meta.env.BASE_URL}${path.replace(/^\//, '')}`;
