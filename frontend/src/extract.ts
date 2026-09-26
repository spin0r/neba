// ─── Extract page: manifest / info / covers + history ──────────────

import { api, AuthError } from './api';
import type { ExtractData } from './api';
import { $, esc, copyText, fmtRes } from './ui';
import { openViewer } from './viewer';

export type Mode = 'manifest' | 'info' | 'covers' | 'screenshots';

interface HistEntry {
  url: string;
  title: string;
  t: number;
}

const HIST_KEY = 'ae_hist';
const LEGACY_COOKIES = 'ae_cookies';
const ADE_COOKIES = 'ae_cookies_ade';
const EA_COOKIES = 'ae_cookies_ea';

let mode: Mode = 'manifest';
let lastData: ExtractData | null = null;

const urlInput = $('urlInput') as HTMLInputElement;
const resultBody = $('resultBody');
const histBody = $('histBody');

export function browserCookies(): { ade: string; ea: string; legacy: string } {
  return {
    ade: localStorage.getItem(ADE_COOKIES) || '',
    ea: localStorage.getItem(EA_COOKIES) || '',
    legacy: localStorage.getItem(LEGACY_COOKIES) || '',
  };
}

// ── History ──
function getHist(): HistEntry[] {
  try {
    return JSON.parse(localStorage.getItem(HIST_KEY) || '[]') as HistEntry[];
  } catch {
    return [];
  }
}

function pushHist(url: string, title: string): void {
  const h = getHist().filter((x) => x.url !== url);
  h.unshift({ url, title: title || '', t: Date.now() });
  localStorage.setItem(HIST_KEY, JSON.stringify(h.slice(0, 20)));
  renderHist();
}

export function renderHist(): void {
  const h = getHist();
  $('histList').innerHTML = h.length
    ? h
        .map(
          (x, i) => `
      <div class="hist-item" data-i="${i}">
        <span class="hist-url">${esc(x.url)}</span>
        <span class="hist-meta">${esc(x.title || '')}</span>
      </div>`,
        )
        .join('')
    : '<div class="hist-item"><span class="hist-meta">Nothing yet — paste a link above.</span></div>';
  document.querySelectorAll('.hist-item[data-i]').forEach((el) => {
    (el as HTMLElement).onclick = () => {
      urlInput.value = getHist()[Number((el as HTMLElement).dataset.i)].url;
      void fetchExtract();
    };
  });
}

// ── Fetch ──
export async function fetchExtract(): Promise<void> {
  const url = urlInput.value.trim();
  if (!url) return;
  histBody.classList.remove('visible');
  resultBody.classList.add('visible');
  resultBody.innerHTML = '<div class="loading"><div class="spinner"></div>Fetching manifest…</div>';
  try {
    const c = browserCookies();
    const r = await api.extract(url, mode, c.ade, c.ea, c.legacy);
    if (!r.success || !r.data) throw new Error(r.error || 'Extraction failed');
    lastData = r.data;
    pushHist(r.data.source_url || url, r.data.movie_title || r.data.title || '');
    render(r.data);
  } catch (e) {
    if (e instanceof AuthError) {
      window.dispatchEvent(new CustomEvent('ae:locked'));
      return;
    }
    resultBody.innerHTML = `<div class="section-label">Error</div><div class="error-box">${esc(
      (e as Error).message,
    )}</div>`;
  }
}

// ── Render ──
function headerLabel(d: ExtractData): { site: string; t: string } {
  const site = d.site || '?';
  const t = d.scene_title
    ? `${d.movie_title} — ${d.scene_title}`
    : d.movie_title || d.title || 'Unknown';
  return { site, t };
}

// ── Keyboard selection: ↑/↓ move, Enter activates, Esc clears ──
let selIndex = -1;

function selectables(): HTMLElement[] {
  return Array.from(resultBody.querySelectorAll<HTMLElement>('#heroCopy, [data-copy], [data-open]'));
}

function paintSelection(): void {
  const items = selectables();
  items.forEach((el, i) => el.classList.toggle('selected', i === selIndex));
  const cur = items[selIndex];
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}

export function resetSelection(): void {
  selIndex = -1;
}

export function markSelected(el: HTMLElement): void {
  const items = selectables();
  const i = items.indexOf(el);
  if (i >= 0) {
    selIndex = i;
    paintSelection();
  }
}

export function moveSelection(dir: 1 | -1): boolean {
  const items = selectables();
  if (!items.length) return false;
  selIndex = selIndex < 0 ? (dir > 0 ? 0 : items.length - 1) : (selIndex + dir + items.length) % items.length;
  paintSelection();
  return true;
}

export function activateSelection(): boolean {
  const items = selectables();
  const cur = selIndex >= 0 ? items[selIndex] : undefined;
  if (!cur) return false;
  cur.click();
  return true;
}

function render(d: ExtractData): void {
  resetSelection();
  if (mode === 'info') return renderInfo(d);
  if (mode === 'covers') return renderCovers(d);
  if (mode === 'screenshots') return renderScreenshots(d);
  return renderManifest(d);
}

function qualityLabel(height: number): string {
  if (height >= 2160) return '4K UHD';
  if (height >= 1080) return 'Full HD';
  if (height >= 720) return 'HD';
  return 'SD';
}

const COPY_ICON = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;

function renderManifest(d: ExtractData): void {
  const { site, t } = headerLabel(d);
  const links = d.preferred_links || [];
  const master = d.manifest_url || '';
  const best = links.length ? links[0] : null;
  $('srcHint').textContent = d.cookies_source ? `via ${d.cookies_source} cookies` : '';

  const heroRight = best
    ? `<div class="hero-value">${best.height}p</div><div class="hero-sub">best stream · click to copy</div><div class="hero-pill">${esc(
        d.duration || '',
      )} · ${esc(fmtRes(d.resolutions))}</div>`
    : `<div class="hero-value small">${esc(master.slice(0, 90))}…</div><div class="hero-sub">master playlist · click to copy</div>`;

  const rows = links
    .map((l, i) => {
      const q = qualityLabel(l.height);
      const isBest = i === 0;
      return `
    <div class="row ${isBest ? 'is-best' : ''}" data-copy="${esc(l.url)}" title="Click to copy ${l.height}p link">
      <div class="row-left">
        <span class="row-name">${l.height}p</span>
        <span class="row-quality">${q}</span>
      </div>
      <div class="row-right">
        <span class="row-action-text">Copy</span>
        <span class="row-copy-icon">${COPY_ICON}</span>
        <span class="kbd">↵</span>
      </div>
    </div>`;
    })
    .join('');

  const idLine = d.scene_id ? `Scene ${esc(String(d.scene_id))}` : `ID ${esc(String(d.movie_id ?? ''))}`;

  resultBody.innerHTML = `
    <div class="section-label">[${esc(site)}] Manifest</div>
    <div class="hero-card" id="heroCopy" title="Click to copy">
      <div class="hero-half">
        <div class="hero-value">${esc(t)}</div>
        <div class="hero-sub">${esc(d.studio || '')}</div>
        <div class="hero-pill">${esc(d.duration || '')} · ${idLine}</div>
      </div>
      <div class="hero-divider"><svg class="hero-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12" /><polyline points="13 6 19 12 13 18" /></svg></div>
      <div class="hero-half">${heroRight}</div>
    </div>
    ${links.length ? `<div class="section-label">Variant streams</div><div class="list">${rows}</div>` : ''}
    ${
      master
        ? `<div class="section-label">Master playlist</div><div class="list">
      <div class="row" data-copy="${esc(master)}" title="Click to copy master URL">
        <div class="row-left">
          <span class="row-name">Master</span>
          <span class="row-quality">HLS</span>
        </div>
        <div class="row-right">
          <span class="row-action-text">Copy</span>
          <span class="row-copy-icon">${COPY_ICON}</span>
          <span class="kbd">↵</span>
        </div>
      </div></div>`
        : ''
    }
    <div class="footer">
      <button class="action-pill-btn" id="btnCopyBest">Copy ${best ? best.height + 'p' : 'manifest'} <span class="action-pill-kbd">↵</span></button>
      <button class="action-pill-btn" id="btnRefresh">Refresh</button>
      ${d.covers && d.covers.length ? `<button class="action-pill-btn" id="btnCovers">Covers</button>` : ''}
    </div>`;

  ($('heroCopy') as HTMLElement).onclick = () =>
    void copyText(best ? best.url : master, best ? `Copied ${best.height}p link` : 'Copied master URL');
  ($('btnCopyBest') as HTMLElement).onclick = () => void copyText(best ? best.url : master, 'Copied');
  ($('btnRefresh') as HTMLElement).onclick = () => void fetchExtract();
  const bc = document.getElementById('btnCovers');
  if (bc) bc.onclick = () => setMode('covers');
  resultBody.querySelectorAll('.row[data-copy]').forEach((r) => {
    (r as HTMLElement).onclick = () => void copyText((r as HTMLElement).dataset.copy || '', 'Copied link');
  });
}

function renderInfo(d: ExtractData): void {
  const { site, t } = headerLabel(d);
  const perf = (d.performers || []).join(', ');
  const scenes = (d.scenes || [])
    .map(
      (s) =>
        `<div class="kv-row"><span class="kv-k">Scene ${s.n}</span><span class="kv-v">${esc(
          (s.performers || []).join(', ') || '—',
        )}</span></div>`,
    )
    .join('');
  resultBody.innerHTML = `
    <div class="section-label">[${esc(site)}] Info</div>
    <div class="kv">
      <div class="kv-row"><span class="kv-k">Title</span><span class="kv-v">${esc(t)}</span></div>
      <div class="kv-row"><span class="kv-k">Studio</span><span class="kv-v">${esc(d.studio || 'Unknown')}</span></div>
      <div class="kv-row"><span class="kv-k">Duration</span><span class="kv-v">${esc(d.duration || '?')}</span></div>
      <div class="kv-row"><span class="kv-k">Resolutions</span><span class="kv-v mono">${esc(fmtRes(d.resolutions))}</span></div>
      ${
        d.scene_count
          ? `<div class="kv-row"><span class="kv-k">Scenes</span><span class="kv-v">${d.scene_count}</span></div>`
          : ''
      }
      ${perf ? `<div class="kv-row"><span class="kv-k">Performers</span><span class="kv-v">${esc(perf)}</span></div>` : ''}
      ${scenes}
    </div>
    <div class="footer">
      <button class="action-pill-btn" id="btnGoManifest">Get manifest <span class="action-pill-kbd">↵</span></button>
    </div>`;
  ($('btnGoManifest') as HTMLElement).onclick = () => setMode('manifest');
}

function renderCovers(d: ExtractData): void {
  const covers = d.covers || [];
  resultBody.innerHTML = `
    <div class="section-label">Covers (${covers.length})</div>
    ${
      covers.length
        ? `<div class="covers">${covers
            .map(
              (c, i) =>
                `<img src="${esc(c)}" data-i="${i}" data-open="${esc(c)}" title="Click to open full size" loading="lazy" />`,
            )
            .join('')}</div>`
        : '<div class="error-box">No covers found for this title.</div>'
    }
    <div class="footer">
      ${covers
        .map(
          (c, i) =>
            `<button class="action-pill-btn" data-copy="${esc(c)}">${
              i === 0 ? 'Front' : i === 1 ? 'Back' : 'Cover ' + (i + 1)
            }</button>`,
        )
        .join('')}
    </div>`;
  resultBody.querySelectorAll('img[data-i]').forEach((img) => {
    (img as HTMLElement).onclick = () =>
      openViewer(
        covers.map((c) => ({ thumb: c, full: c })),
        Number((img as HTMLElement).dataset.i),
      );
  });
  resultBody.querySelectorAll('button[data-copy]').forEach((b) => {
    (b as HTMLElement).onclick = () => void copyText((b as HTMLElement).dataset.copy || '', 'Copied cover URL');
  });
}

function renderScreenshots(d: ExtractData): void {
  const shots = d.screenshots || [];
  resultBody.innerHTML = `
    <div class="section-label">Screenshots (${shots.length})</div>
    ${
      shots.length
        ? `<div class="shots">${shots
            .map(
              (s, i) =>
                `<img src="${esc(s.thumb)}" data-full="${esc(s.full)}" data-open="${esc(
                  s.full,
                )}" title="Click for full size (${i + 1}/${shots.length})" loading="lazy" />`,
            )
            .join('')}</div>`
        : '<div class="error-box">No screenshots found. Scene pages carry stills — movie pages do not.</div>'
    }
    ${
      shots.length
        ? `<div class="footer">
      <button class="action-pill-btn" id="btnCopyShots">Copy all URLs</button>
    </div>`
        : ''
    }`;
  resultBody.querySelectorAll('.shots img').forEach((img, i) => {
    (img as HTMLElement).onclick = () => openViewer(shots, i);
  });
  const btn = document.getElementById('btnCopyShots');
  if (btn)
    btn.onclick = () => void copyText(shots.map((s) => s.full).join('\n'), `Copied ${shots.length} URLs`);
}

// ── Modes ──
export function setMode(next: Mode): void {
  mode = next;
  document.querySelectorAll('.mode-pill').forEach((x) =>
    x.classList.toggle('active', (x as HTMLElement).dataset.mode === next),
  );
  if (lastData) render(lastData);
}

const MODES: Mode[] = ['manifest', 'info', 'covers', 'screenshots'];

export function cycleMode(dir: 1 | -1): void {
  const i = MODES.indexOf(mode);
  setMode(MODES[(i + dir + MODES.length) % MODES.length]);
}

export function initExtractPage(): void {
  document.querySelectorAll('.mode-pill').forEach((p) => {
    ((p as HTMLElement).onclick = () => setMode(((p as HTMLElement).dataset.mode as Mode) || 'manifest'));
  });
  // Keep mouse clicks and keyboard selection in sync
  resultBody.addEventListener('click', (e) => {
    const t = (e.target as HTMLElement).closest('#heroCopy, [data-copy], [data-open]');
    if (t) markSelected(t as HTMLElement);
  });
  urlInput.addEventListener('input', () => {
    if (!urlInput.value.trim()) {
      resultBody.classList.remove('visible');
      histBody.classList.add('visible');
    }
  });
  ($('clearHist') as HTMLElement).onclick = () => {
    localStorage.removeItem(HIST_KEY);
    renderHist();
  };
}

export function showExtractChrome(visible: boolean): void {
  (document.querySelector('.input-row') as HTMLElement).style.display = visible ? '' : 'none';
  $('modeRow').style.display = visible ? '' : 'none';
}

export function hideExtractBodies(): void {
  resultBody.classList.remove('visible');
  histBody.classList.remove('visible');
}

export function refreshExtractVisibility(authed: boolean): void {
  const hasResult = resultBody.innerHTML !== '';
  resultBody.classList.toggle('visible', hasResult);
  histBody.classList.toggle('visible', !hasResult && !urlInput.value.trim() && authed);
}
