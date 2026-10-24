import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { assetUrl, parseCatalog } from './catalog';
import { recommendLocal } from './recommend';
import type { Catalog, Movie } from './catalog';

type IconName = 'search' | 'arrow' | 'bookmark' | 'close' | 'external' | 'filter' | 'check' | 'film';
function Icon({ name, size = 20, filled = false }: { name: IconName; size?: number; filled?: boolean }) {
  const paths: Record<IconName, ReactNode> = {
    search: <><circle cx="10.7" cy="10.7" r="6.7" /><path d="m16 16 4.5 4.5" /></>,
    arrow: <><path d="M4 12h15M13 5l7 7-7 7" /></>,
    bookmark: <path d="M6 4h12v17l-6-4-6 4z" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    external: <><path d="M14 4h6v6M20 4 10 14M10 5H5v14h14v-5" /></>,
    filter: <><path d="M4 6h16M4 12h16M4 18h16" /><path d="M9 3v6M16 9v6M9 15v6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    film: <><rect x="3" y="4" width="18" height="16" rx="1" /><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
function readSaved(): string[] {
  try { const value: unknown = JSON.parse(localStorage.getItem('frame:watchlist') || '[]'); return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
  catch { return []; }
}
function Poster({ movie, className = '' }: { movie: Movie; className?: string }) {
  const [failed, setFailed] = useState(false);
  return movie.poster && !failed ? <img className={className} src={assetUrl(movie.poster)} alt={`${movie.title} poster`} loading="lazy" onError={() => setFailed(true)} /> : <div className={`poster-fallback ${className}`}><Icon name="film" size={40} /><span>{movie.title}</span><small>Artwork unavailable</small></div>;
}
function Modal({ movie, demo, saved, onSave, onClose }: { movie: Movie; demo: boolean; saved: boolean; onSave: () => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.querySelector<HTMLElement>('button')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key === 'Tab') {
        const nodes = Array.from(ref.current?.querySelectorAll<HTMLElement>('button, a[href], [tabindex="0"]') || []);
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, [onClose]);
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="movie-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title" ref={ref}>
      <button className="close-modal icon-button" aria-label="Close details" onClick={onClose}><Icon name="close" /></button>
      <div className="modal-art"><Poster movie={movie} /></div>
      <div className="modal-copy">
        <p className="eyebrow">{demo ? 'A FRAME ORIGINAL DEMO' : 'IN THE COLLECTION'}</p>
        <h2 id="detail-title">{movie.title}</h2>
        <div className="detail-meta"><span>{movie.year ?? 'Year unconfirmed'}</span><span className="meta-dot">•</span><span>{movie.genres.join(' / ') || 'Genre unconfirmed'}</span></div>
        <p className="synopsis">{movie.synopsis || 'A synopsis has not been provided for this film.'}</p>
        <button className={`save-detail ${saved ? 'is-saved' : ''}`} onClick={onSave}><Icon name={saved ? 'check' : 'bookmark'} />{saved ? 'Saved to watchlist' : 'Add to watchlist'}</button>
        <div className="editions-heading"><h3>Available editions</h3><span>{movie.links.length} {movie.links.length === 1 ? 'link' : 'links'}</span></div>
        {demo && <p className="demo-link-note">Demo links lead to example.org. No film files are hosted or supplied.</p>}
        <div className="edition-list">{movie.links.length ? movie.links.map((link, i) => <a href={link.url} key={`${link.url}-${i}`} target="_blank" rel="noopener noreferrer nofollow" className="edition"><span className="quality-icon">{link.quality || 'Unspecified'}</span><span className="edition-info"><strong>{link.label}</strong><small>{link.size || 'Size not provided'} · {new URL(link.url).hostname}</small></span><Icon name="external" size={18} /></a>) : <div className="no-links">No cleared external links are available for this film.</div>}</div>
        <p className="source-note">From {Array.from(new Set(movie.sources.map(source => source.channelName))).join(' & ') || 'the collection'} · {movie.rights.poster === 'none' ? 'No poster supplied' : 'Artwork cleared'}</p>
      </div>
    </div>
  </div>;
}
export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState('');
  const [request, setRequest] = useState(0);
  const [search, setSearch] = useState('');
  const [genre, setGenre] = useState('all');
  const [year, setYear] = useState('all');
  const [quality, setQuality] = useState('all');
  const [channel, setChannel] = useState('all');
  const [sort, setSort] = useState('curated');
  const [tab, setTab] = useState<'discover' | 'watchlist'>('discover');
  const [saved, setSaved] = useState<string[]>(readSaved);
  const [saveNotice, setSaveNotice] = useState('');
  const [selected, setSelected] = useState<Movie | null>(null);
  const [remoteIds, setRemoteIds] = useState<string[] | null>(null);
  const [limit, setLimit] = useState(12);
  const collection = useRef<HTMLElement>(null);
  const about = useRef<HTMLElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError(''); setCatalog(null);
    fetch(assetUrl('/data/movies.json'), { signal: controller.signal }).then(response => { if (!response.ok) throw new Error(`Catalog request failed (${response.status}).`); return response.json(); }).then(value => setCatalog(parseCatalog(value))).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'The catalog could not be loaded.'); });
    return () => controller.abort();
  }, [request]);
  useEffect(() => { setLimit(12); }, [search, genre, year, quality, channel, sort, tab]);
  const toggleSave = (movie: Movie) => {
    const updated = saved.includes(movie.id) ? saved.filter(id => id !== movie.id) : [...saved, movie.id];
    setSaved(updated);
    try { localStorage.setItem('frame:watchlist', JSON.stringify(updated)); setSaveNotice(`${movie.title} ${updated.includes(movie.id) ? 'saved to' : 'removed from'} your watchlist.`); }
    catch { setSaveNotice('Saved for this session. Browser storage is unavailable.'); }
  };
  const movies = catalog?.movies || [];
  useEffect(() => {
    const base = import.meta.env.VITE_RECOMMENDATIONS_API_URL?.trim();
    if (!base || !catalog) { setRemoteIds(null); return; }
    const controller = new AbortController();
    try {
      const url = new URL(base.replace(/\/+$/, '') + '/recommendations');
      url.searchParams.set('seed', saved.slice(0, 50).join(','));
      url.searchParams.set('limit', '6');
      fetch(url, { signal: controller.signal }).then(response => {
        if (!response.ok) throw new Error('Recommendations unavailable');
        return response.json();
      }).then(data => {
        if (!controller.signal.aborted && Array.isArray(data.recommendations)) {
          setRemoteIds(data.recommendations.map((entry: { id?: unknown }) => entry.id).filter((id: unknown): id is string => typeof id === 'string'));
        }
      }).catch(() => { if (!controller.signal.aborted) setRemoteIds(null); });
    } catch { setRemoteIds(null); }
    return () => controller.abort();
  }, [catalog, saved]);
  const recommendedMovies = useMemo(() => {
    const seen = new Set(saved);
    return [...(remoteIds || []).map(id => movies.find(movie => movie.id === id)), ...recommendLocal(movies, saved, 6)]
      .filter((movie): movie is Movie => !!movie)
      .filter(movie => { if (seen.has(movie.id)) return false; seen.add(movie.id); return true; }).slice(0, 6);
  }, [movies, saved, remoteIds]);
  const genres = Array.from(new Set(movies.flatMap(movie => movie.genres))).sort();
  const years = Array.from(new Set(movies.map(movie => movie.year).filter((value): value is number => value !== null))).sort((a, b) => b - a);
  const qualities = Array.from(new Set(movies.flatMap(movie => movie.links.map(link => link.quality).filter((value): value is string => !!value)))).sort();
  const channels = Array.from(new Map(movies.flatMap(movie => movie.sources.map(source => [source.channelId, source.channelName] as const))).entries()).sort((a,b) => a[1].localeCompare(b[1]));
  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return movies.filter(movie => (tab === 'discover' || saved.includes(movie.id)) && (!query || [movie.title, movie.synopsis, ...movie.genres].join(' ').toLocaleLowerCase().includes(query)) && (genre === 'all' || movie.genres.includes(genre)) && (year === 'all' || String(movie.year) === year) && (quality === 'all' || (quality === 'unspecified' ? movie.links.length === 0 || movie.links.some(link => link.quality === null) : movie.links.some(link => link.quality === quality))) && (channel === 'all' || movie.sources.some(source => source.channelId === channel))).sort((a, b) => sort === 'title' ? a.title.localeCompare(b.title) : sort === 'newest' ? (b.year ?? 0) - (a.year ?? 0) || a.title.localeCompare(b.title) : sort === 'oldest' ? (a.year ?? 9999) - (b.year ?? 9999) || a.title.localeCompare(b.title) : 0);
  }, [movies, search, genre, year, quality, channel, sort, tab, saved]);
  const hasFilters = search !== '' || genre !== 'all' || year !== 'all' || quality !== 'all' || channel !== 'all';
  const clearFilters = () => { setSearch(''); setGenre('all'); setYear('all'); setQuality('all'); setChannel('all'); };
  const goCollection = (nextTab: 'discover' | 'watchlist' = 'discover') => { setTab(nextTab); collection.current?.scrollIntoView({ behavior: 'smooth' }); };
  return <>
    <a className="skip-link" href="#collection">Skip to collection</a>
    <header className="site-header"><div className="header-inner"><a href="#" className="wordmark" aria-label="FRAME home">FRA<span className="logo-m">M</span>E<span className="logo-dot">®</span></a><nav aria-label="Main navigation"><button className="nav-active" onClick={() => goCollection()}>The collection</button><button onClick={() => about.current?.scrollIntoView({ behavior: 'smooth' })}>Our story</button></nav><button className="header-watchlist" onClick={() => goCollection('watchlist')}><Icon name="bookmark" size={17} /><span>Your watchlist</span><span className="saved-count">{saved.filter(id => movies.some(m => m.id === id)).length}</span></button></div></header>
    <main>
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-art" role="img" aria-label="Original abstract landscape of a quiet green sea and amber sun" />
        <div className="hero-shade" />
        <div className="hero-content"><p className="eyebrow"><span className="tiny-cross">✳</span> A WORLD OF STORIES. ONE COLLECTION.</p><h1 id="hero-title">Some stories<br />stay with <em>you.</em></h1><p className="hero-description">The unexpected. The unforgettable. The just-one-more.<br className="desktop-break" /> Find your next great film, all in one place.</p><button className="primary-button" onClick={() => goCollection()}>Explore the collection <Icon name="arrow" /></button><div className="hero-bottom"><span className="mini-rule" /><span>CURATED FOR THE CURIOUS</span></div></div>
        <div className="hero-caption"><span className="caption-line" /><p>AN ORIGINAL FRAME LANDSCAPE<br /><strong>A little room for imagination.</strong></p><span className="hero-coordinate">35° N · 139° E</span></div>
        <span className="vertical-label">THE ART OF FINDING A GOOD FILM</span>
      </section>
      <div className="collection-note"><span className="note-symbol">✳</span><p>{catalog?.kind === 'public' ? 'Independently curated. Cleared for sharing. Ready to discover.' : 'An original demo collection. Fictional films, original artwork, real possibilities.'}</p><span className="note-right">MADE FOR FILM PEOPLE <Icon name="arrow" size={16} /></span></div>
      <section className="collection section-width" id="collection" aria-labelledby="collection-title" ref={collection}>
        <div className="section-heading"><div><p className="eyebrow light-eyebrow">THE COLLECTION <span>/{String(movies.length).padStart(2,'0')}</span></p><h2 id="collection-title">Your next great <em>watch.</em></h2></div><p className="section-description">A different mood. A new perspective.<br />There’s a story here for you.</p></div>
        <div className="collection-controls"><div className="tabs" aria-label="Collection view"><button className={tab === 'discover' ? 'tab active' : 'tab'} aria-pressed={tab === 'discover'} onClick={() => setTab('discover')}>Discover <span>{movies.length}</span></button><button className={tab === 'watchlist' ? 'tab active' : 'tab'} aria-pressed={tab === 'watchlist'} onClick={() => setTab('watchlist')}>Watchlist <span>{saved.filter(id => movies.some(m => m.id === id)).length}</span></button></div><label className="search-field"><Icon name="search" size={19} /><input aria-label="Search films" type="search" placeholder="Search films, moods, genres…" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
        <div className="filter-row"><span className="filter-label"><Icon name="filter" size={17} />Filter by</span><label><span className="sr-only">Genre</span><select aria-label="Genre" value={genre} onChange={event => setGenre(event.target.value)}><option value="all">All genres</option>{genres.map(item => <option key={item}>{item}</option>)}</select></label><label><span className="sr-only">Year</span><select aria-label="Year" value={year} onChange={event => setYear(event.target.value)}><option value="all">All years</option>{years.map(item => <option key={item}>{item}</option>)}{movies.some(movie => movie.year === null) && <option value="null">Unconfirmed year</option>}</select></label><label><span className="sr-only">Quality</span><select aria-label="Quality" value={quality} onChange={event => setQuality(event.target.value)}><option value="all">All qualities</option>{qualities.map(item => <option key={item}>{item}</option>)}{movies.some(movie => movie.links.length === 0 || movie.links.some(link => link.quality === null)) && <option value="unspecified">Unspecified quality</option>}</select></label><label><span className="sr-only">Channel</span><select aria-label="Channel" value={channel} onChange={event => setChannel(event.target.value)}><option value="all">All channels</option>{channels.map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select></label><div className="sort-control"><label htmlFor="sort">Sort:</label><select id="sort" aria-label="Sort films" value={sort} onChange={event => setSort(event.target.value)}><option value="curated">Curated order</option><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="title">Title A–Z</option></select></div></div>
        {hasFilters && <div className="active-filter-row"><span>{filtered.length} matching {filtered.length === 1 ? 'film' : 'films'}</span><button onClick={clearFilters}>Clear filters <Icon name="close" size={14} /></button></div>}
        {!catalog && !error && <div className="loading-state" role="status"><span className="loading-ring" />Finding your next great story…</div>}
        {error && <div className="empty-state" role="alert"><Icon name="film" size={34} /><h3>The collection couldn’t load.</h3><p>{error}</p><button className="dark-button" onClick={() => setRequest(value => value + 1)}>Try again <Icon name="arrow" size={17} /></button></div>}
        {catalog && filtered.length === 0 && <div className="empty-state"><Icon name={tab === 'watchlist' && !hasFilters ? 'bookmark' : 'search'} size={34} /><h3>{tab === 'watchlist' && !hasFilters ? 'A little space for your next favorites.' : 'No films found. Yet.'}</h3><p>{tab === 'watchlist' && !hasFilters ? 'Save any film with the bookmark icon. Your watchlist stays in this browser.' : 'Try another title, or give your filters a little more room.'}</p><button className="dark-button" onClick={() => { clearFilters(); if (tab === 'watchlist' && !hasFilters) setTab('discover'); }}>{tab === 'watchlist' && !hasFilters ? 'Discover films' : 'Clear filters'}<Icon name="arrow" size={17} /></button></div>}
        <div className="movie-grid">{filtered.slice(0, limit).map((movie, index) => <article className="movie-card" key={movie.id}><div className="poster-wrap"><button className="poster-button" onClick={() => setSelected(movie)} aria-label={`View ${movie.title}`}><Poster movie={movie} /><span className="poster-scrim" /><span className="view-film">View film <Icon name="arrow" size={17} /></span></button><span className="poster-index">{String(index + 1).padStart(2, '0')}</span><button className={`bookmark-button ${saved.includes(movie.id) ? 'saved' : ''}`} onClick={() => toggleSave(movie)} aria-label={`${saved.includes(movie.id) ? 'Remove' : 'Save'} ${movie.title}`} aria-pressed={saved.includes(movie.id)}><Icon name={saved.includes(movie.id) ? 'check' : 'bookmark'} size={16} /></button>{movie.links.some(link => link.quality) && <span className="card-quality">{movie.links.find(link => link.quality)?.quality}</span>}</div><div className="card-meta"><span>{movie.year ?? 'YEAR TBC'}</span><span>{movie.genres[0] || 'UNCATEGORIZED'}</span></div><button className="card-title" onClick={() => setSelected(movie)}>{movie.title}</button><p className="card-description">{movie.genres.slice(1).join(' · ') || 'A story worth discovering'}</p></article>)}</div>
        {catalog && filtered.length > 0 && <div className="collection-bottom"><span>Showing {Math.min(limit, filtered.length)} of {filtered.length} films</span>{filtered.length > limit ? <button className="outline-button" onClick={() => setLimit(value => value + 12)}>More stories await <Icon name="arrow" size={17} /></button> : <span className="end-note">GOOD STORIES NEVER REALLY END <span>✳</span></span>}</div>}
      </section>
      {catalog && tab === 'discover' && recommendedMovies.length > 0 && <section className="collection section-width" aria-labelledby="recommendations-title">
        <div className="section-heading"><div><p className="eyebrow light-eyebrow">A LITTLE INSPIRATION</p><h2 id="recommendations-title">{saved.length ? 'Inspired by your' : 'More to'} <em>{saved.length ? 'watchlist.' : 'explore.'}</em></h2></div><p className="section-description">Suggestions based on movie genres, titles and release years — no tracking.</p></div>
        <div className="movie-grid">{recommendedMovies.map(movie => <article key={movie.id} className="movie-card"><div className="poster-wrap"><button className="poster-button" onClick={() => setSelected(movie)} aria-label={`Open recommendation for ${movie.title}`}><Poster movie={movie} /><span className="poster-scrim" /><span className="view-film">View film <Icon name="arrow" size={17} /></span></button></div><div className="card-meta"><span>{movie.year ?? 'YEAR TBC'}</span><span>{movie.genres[0] || 'UNCATEGORIZED'}</span></div><button className="card-title" onClick={() => setSelected(movie)}>{movie.title}</button></article>)}</div>
      </section>}
      <section className="about-band" ref={about} id="our-story"><div className="section-width about-inner"><span className="about-asterisk">✳</span><div><p className="eyebrow">LESS SCROLLING. MORE DISCOVERING.</p><h2>For the love<br />of the <em>story.</em></h2></div><div className="about-copy"><p>Great films take us somewhere. FRAME brings them together — a thoughtful collection to explore, save, and return to.</p><p className="about-small">{catalog?.kind === 'public' ? 'Only reviewed records and permitted artwork belong in this collection. External links open on their original provider.' : 'You’re exploring an original demo. Every film and poster here was created for this site. Imported channel archives stay private until their distribution and artwork rights are reviewed.'}</p><button onClick={() => goCollection()} className="text-link">Find a story <Icon name="arrow" size={18} /></button></div></div></section>
    </main>
    <footer className="site-footer section-width"><a href="#" className="wordmark footer-logo">FRAME<span className="logo-dot">®</span></a><span>A world of stories. A little closer.</span><span className="footer-status"><span />{catalog?.kind === 'public' ? 'REVIEWED COLLECTION' : 'ORIGINAL DEMO COLLECTION'}</span><a href="#collection" className="back-top">Back to films ↑</a></footer>
    <div className="sr-only" role="status" aria-live="polite">{saveNotice}</div>
    {selected && <Modal movie={selected} demo={catalog?.kind === 'demo'} saved={saved.includes(selected.id)} onSave={() => toggleSave(selected)} onClose={() => setSelected(null)} />}
  </>;
}
