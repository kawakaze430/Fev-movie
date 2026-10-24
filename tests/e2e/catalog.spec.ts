import { test, expect, type Page } from '@playwright/test';

// These records are authored fixtures, never material copied from a Telegram archive.
const fixture = {
  schemaVersion: 1,
  generatedAt: '2026-10-23T00:00:00Z',
  kind: 'demo',
  movies: [
    { id: 'aurora-drift', title: 'Aurora Drift', year: 2024, genres: ['Science Fiction', 'Adventure'], synopsis: 'A navigator follows an impossible signal.', poster: null, links: [{ label: 'Synthetic preview', quality: '1080p', url: 'https://example.org/aurora', size: '1.2 GB' }], sources: [{ channelId: 'north', channelName: 'North Collection', messageId: '1' }], rights: { distribution: 'cleared', poster: 'none', evidence: 'Authored browser test fixture' } },
    { id: 'paper-birds', title: 'Paper Birds', year: 2021, genres: ['Drama'], synopsis: 'A paper artist rediscovers her hometown.', poster: null, links: [{ label: 'Synthetic preview', quality: '720p', url: 'https://example.org/birds', size: '700 MB' }], sources: [{ channelId: 'south', channelName: 'South Collection', messageId: '2' }], rights: { distribution: 'cleared', poster: 'none', evidence: 'Authored browser test fixture' } },
    { id: 'night-bloom', title: 'Night Bloom', year: 2024, genres: ['Drama', 'Thriller'], synopsis: 'A quiet greenhouse hides a mystery.', poster: null, links: [{ label: 'Synthetic preview', quality: null, url: 'https://example.org/bloom', size: '2 GB' }], sources: [{ channelId: 'north', channelName: 'North Collection', messageId: '3' }], rights: { distribution: 'cleared', poster: 'none', evidence: 'Authored browser test fixture' } },
  ],
};

async function loadFixture(page: Page, data: unknown = fixture) {
  await page.route('**/data/movies.json', route => route.fulfill({ json: data }));
  await page.goto('/');
  await expect(page.getByRole('searchbox', { name: 'Search films' })).toBeVisible();
}

const cards = (page: Page) => page.getByRole('button', { name: /^View / });

async function readyForScreenshot(page: Page) {
  await page.evaluate(async () => {
    const images = Array.from(document.images);
    images.forEach(image => { image.loading = 'eager'; });
    await Promise.all(images.map(image => image.decode().catch(() => {})));
    await document.fonts.ready;
  });
  await expect.poll(() => page.evaluate(() => Array.from(document.images).every(image => image.complete && image.naturalWidth > 0))).toBe(true);
}

test('searches titles and restores the collection after clearing', async ({ page }) => {
  await loadFixture(page);
  await expect(cards(page)).toHaveCount(3);
  await page.getByRole('searchbox', { name: 'Search films' }).fill('paper');
  await expect(page.getByRole('button', { name: 'View Paper Birds', exact: true })).toBeVisible();
  await expect(cards(page)).toHaveCount(1);
  await page.getByRole('searchbox', { name: 'Search films' }).fill('');
  await expect(cards(page)).toHaveCount(3);
});

test('combines genre, year, quality and channel filters', async ({ page }) => {
  await loadFixture(page);
  await page.getByRole('combobox', { name: 'Genre', exact: true }).selectOption({ label: 'Drama' });
  await expect(cards(page)).toHaveCount(2);
  await page.getByRole('combobox', { name: 'Year', exact: true }).selectOption({ label: '2021' });
  await page.getByRole('combobox', { name: 'Quality', exact: true }).selectOption({ label: '720p' });
  await page.getByRole('combobox', { name: 'Channel', exact: true }).selectOption({ label: 'South Collection' });
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'View Paper Birds', exact: true })).toBeVisible();
});

test('keeps quality unspecified even when a file size exists', async ({ page }) => {
  await loadFixture(page);
  await page.getByRole('combobox', { name: 'Quality', exact: true }).selectOption({ label: 'Unspecified quality' });
  await expect(cards(page)).toHaveCount(1);
  await page.getByRole('button', { name: 'View Night Bloom', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Unspecified', { exact: true })).toBeVisible();
  await expect(dialog.getByText(/2 GB/)).toBeVisible();
  await expect(dialog.getByText(/1080p|720p|4K/)).toHaveCount(0);
});

test('sorts movies alphabetically', async ({ page }) => {
  await loadFixture(page);
  const sort = page.getByRole('combobox', { name: 'Sort films' });
  const option = sort.locator('option').filter({ hasText: /title|a.*z/i }).first();
  await sort.selectOption(await option.getAttribute('value') || await option.innerText());
  await expect(cards(page).first()).toHaveAccessibleName('View Aurora Drift');
});

test('shows a useful empty search state', async ({ page }) => {
  await loadFixture(page);
  await page.getByRole('searchbox', { name: 'Search films' }).fill('no-such-movie-12345');
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByText(/no films|no matches|nothing found/i).first()).toBeVisible();
});

test('opens details and exposes the explicit quality without inventing it', async ({ page }) => {
  await loadFixture(page);
  await page.getByRole('button', { name: 'View Aurora Drift', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText('A navigator follows an impossible signal.')).toBeVisible();
  const link = dialog.getByRole('link', { name: /1080p/ });
  await expect(link).toHaveAttribute('href', 'https://example.org/aurora');
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', /noopener/);
  await expect(dialog.getByText(/1\.2 GB/)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'View Aurora Drift', exact: true })).toBeFocused();
});

test('traps keyboard focus inside details', async ({ page }) => {
  await loadFixture(page);
  await page.getByRole('button', { name: 'View Paper Birds', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  for (let index = 0; index < 12; index++) {
    await page.keyboard.press('Tab');
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  }
  await page.getByRole('button', { name: 'Close details' }).click();
  await expect(dialog).not.toBeVisible();
});

test('persists saved films and supports removing them', async ({ page }) => {
  await loadFixture(page);
  await page.getByRole('button', { name: 'Save Paper Birds', exact: true }).click();
  await page.reload();
  await page.getByRole('button', { name: /^Watchlist \d+$/ }).click();
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'View Paper Birds', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Remove Paper Birds', exact: true }).click();
  await expect(cards(page)).toHaveCount(0);
});

test('handles an empty cleared catalog', async ({ page }) => {
  await loadFixture(page, { ...fixture, kind: 'public', movies: [] });
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByText(/no films|no matches|nothing found|collection.*empty/i).first()).toBeVisible();
});

test('rejects uncleared records', async ({ page }) => {
  const data = structuredClone(fixture);
  data.movies[0].rights.distribution = 'pending';
  await page.route('**/data/movies.json', route => route.fulfill({ json: data }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(cards(page)).toHaveCount(0);
});

test('rejects executable external links', async ({ page }) => {
  const data = structuredClone(fixture);
  data.movies[0].links[0].url = 'javascript:alert(1)';
  await page.route('**/data/movies.json', route => route.fulfill({ json: data }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
});

for (const [name, url] of [
  ['abbreviated loopback hosts', 'http://127.1/private'],
  ['localhost destinations', 'https://localhost/private'],
  ['whitespace-padded URLs', ' https://example.org/private'],
] as const) {
  test(`rejects ${name} in catalog links`, async ({ page }) => {
    const data = structuredClone(fixture);
    data.movies[0].links[0].url = url;
    await page.route('**/data/movies.json', route => route.fulfill({ json: data }));
    await page.goto('/');
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(cards(page)).toHaveCount(0);
  });
}

test('rejects private source fields in public catalog records', async ({ page }) => {
  const data = structuredClone(fixture);
  const movie = data.movies[0] as typeof data.movies[number] & { rawText: string };
  movie.rawText = 'Synthetic private source text that must not enter a public catalog.';
  await page.route('**/data/movies.json', route => route.fulfill({ json: data }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByText(movie.rawText, { exact: true })).toHaveCount(0);
});

test('renders untrusted markup as text', async ({ page }) => {
  const data = structuredClone(fixture);
  data.movies[0].title = '<img src=x onerror=alert(1)>';
  let dialogs = 0;
  page.on('dialog', async dialog => { dialogs++; await dialog.dismiss(); });
  await loadFixture(page, data);
  await expect(page.getByRole('button', { name: 'View <img src=x onerror=alert(1)>', exact: true })).toBeVisible();
  await expect(page.locator('img[onerror]')).toHaveCount(0);
  expect(dialogs).toBe(0);
});

test('recovers from a network failure using retry', async ({ page }) => {
  let failing = true;
  await page.route('**/data/movies.json', async route => {
    if (failing) return route.fulfill({ status: 503, body: 'Temporarily unavailable' });
    return route.fulfill({ json: fixture });
  });
  await page.goto('/');
  await expect(page.getByRole('alert')).toBeVisible();
  failing = false;
  await page.getByRole('button', { name: /try again|retry/i }).click();
  await expect(cards(page)).toHaveCount(3);
});

test('shows loading while waiting for catalog data', async ({ page }) => {
  let respond: () => void = () => {};
  const ready = new Promise<void>(resolve => { respond = resolve; });
  await page.route('**/data/movies.json', async route => { await ready; await route.fulfill({ json: fixture }); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('status').filter({ hasText: 'Finding your next great story' })).toBeVisible();
  respond();
  await expect(cards(page)).toHaveCount(3);
});

test('mobile layout fits the screen and details remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await loadFixture(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'View Aurora Drift', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Close details' }).click();
});

test('desktop demo screenshot comparison', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto('/');
  await expect(page.getByRole('searchbox', { name: 'Search films' })).toBeVisible();
  await readyForScreenshot(page);
  await expect(page).toHaveScreenshot('catalog-desktop.png', { fullPage: true });
});

test('mobile demo screenshot comparison', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('searchbox', { name: 'Search films' })).toBeVisible();
  await readyForScreenshot(page);
  await expect(page).toHaveScreenshot('catalog-mobile.png', { fullPage: true });
});
