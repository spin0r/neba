// ─── Cookies page: per-site boxes, auto-store, Thpaste sync ───────

import { api } from './api';
import type { Site } from './api';
import { $, esc, toast } from './ui';

interface CookieSite {
  site: Site;
  label: string;
  host: string;
  store: string;
  file: string;
}

export const COOKIE_SITES: CookieSite[] = [
  { site: 'ade', label: 'AdultDVDEmpire', host: 'adultdvdempire.com', store: 'ae_cookies_ade', file: 'adecookies.txt' },
  { site: 'ea', label: 'Elegant Angel', host: 'elegantangel.com', store: 'ae_cookies_ea', file: 'eacookies.txt' },
  { site: 'dvd', label: 'DVDErotik', host: 'us.dvderotik.com', store: 'ae_cookies_dvd', file: 'dvdcookies.txt' },
];

const PREFIX = 'pg';
let built = false;

function storeCookies(cfg: CookieSite, value: string, quiet = false): boolean {
  if (value && !value.includes('etoken')) {
    if (!quiet) toast('No etoken found in pasted cookies', true);
    return false;
  }
  if (value) localStorage.setItem(cfg.store, value);
  else localStorage.removeItem(cfg.store);
  return true;
}

function tpStatus(site: Site, msg: string, cls = ''): void {
  const el = document.querySelector(`#${PREFIX}-tp-${site}`);
  if (el) {
    el.textContent = msg;
    el.className = 'tp-status' + (cls ? ' ' + cls : '');
  }
}

function setPasteLink(site: Site, url?: string): void {
  const a = document.querySelector(`#${PREFIX}-tp-link-${site}`) as HTMLAnchorElement | null;
  if (!a) return;
  if (url) {
    a.href = url;
    a.hidden = false;
  } else {
    a.removeAttribute('href');
    a.hidden = true;
  }
}

async function pushThpaste(site: Site, content: string): Promise<boolean> {
  tpStatus(site, 'pushing…');
  const r = await api.thpastePush(site, content).catch(() => null);
  if (r && r.success) {
    tpStatus(site, 'Thpaste updated', 'ok');
    setPasteLink(site, r.url || r.custom_url || r.raw_url);
    return true;
  }
  tpStatus(site, (r && r.error) || 'push failed', 'err');
  if (r && r.error && !r.error.includes('No Thpaste API key configured')) toast(r.error, true);
  return false;
}

async function pullThpaste(site: Site): Promise<void> {
  const cfg = COOKIE_SITES.find((x) => x.site === site);
  if (!cfg) return;
  tpStatus(site, 'pulling…');
  const r = await api.thpastePull(site).catch(() => null);
  const st = r && r[site];
  if (!st || !st.configured) {
    tpStatus(site, 'no Thpaste API key configured', 'err');
    return;
  }
  if (st.error) {
    tpStatus(site, st.error, 'err');
    return;
  }
  const content = (st.content || '').trim();
  if (!content.includes('etoken')) {
    tpStatus(site, 'paste has no cookies', 'err');
    return;
  }
  const area = document.querySelector(`#${PREFIX}-area-${site}`) as HTMLTextAreaElement | null;
  if (area) area.value = content;
  storeCookies(cfg, content, true);
  setPasteLink(site, st.url || st.custom_url || st.raw_url);
  tpStatus(site, 'loaded from Thpaste', 'ok');
  toast(`${cfg.label} loaded from Thpaste`);
}

function boxesHTML(): string {
  return COOKIE_SITES.map(
    (s) => `
    <div class="cookie-box" data-site="${s.site}">
      <div class="cookie-box-title"><span class="dot" id="${PREFIX}-dot-${s.site}"></span>${s.label}</div>
      <div class="cookie-box-sub">${s.host} → Netscape export</div>
      <textarea class="cookie-area" id="${PREFIX}-area-${s.site}" placeholder="# Netscape HTTP Cookie File&#10;...paste ${
      s.host
    } cookies...">${esc(localStorage.getItem(s.store) || '')}</textarea>
      <div class="cookie-status-line" id="${PREFIX}-status-${s.site}">Checking server session…</div>
      <div class="modal-actions">
        <button class="btn" data-act="import">Import file</button>
        <button class="btn" data-act="export">Export</button>
        <button class="btn danger" data-act="clear">Clear</button>
        <button class="btn" data-act="server">Server</button>
        <button class="btn primary" data-act="save">Save</button>
      </div>
      <div class="tp-row">
        <button class="btn" data-act="pull">↓ Thpaste</button>
        <button class="btn" data-act="push">↑ Thpaste</button>
        <a class="tp-link" id="${PREFIX}-tp-link-${s.site}" target="_blank" rel="noopener noreferrer" hidden>Raw ↗</a>
        <span class="tp-status" id="${PREFIX}-tp-${s.site}"></span>
      </div>
      <input type="file" class="mFile" accept=".txt,.cookies" style="display:none" />
    </div>`,
  ).join('');
}

function wireBoxes(root: ParentNode): void {
  root.querySelectorAll('.cookie-box').forEach((box) => {
    const site = (box as HTMLElement).dataset.site as Site;
    const cfg = COOKIE_SITES.find((x) => x.site === site);
    if (!cfg) return;
    const area = box.querySelector('textarea') as HTMLTextAreaElement;
    const fileInput = box.querySelector('.mFile') as HTMLInputElement;
    let debounce: ReturnType<typeof setTimeout> | undefined;

    area.addEventListener('paste', () => {
      setTimeout(() => {
        const v = area.value.trim();
        if (!storeCookies(cfg, v, true)) return;
        toast(`${cfg.label} cookies stored — tap Server to persist`);
        void pushThpaste(site, v);
      }, 50);
    });
    area.addEventListener('input', () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        const v = area.value.trim();
        if (v && v.includes('etoken') && storeCookies(cfg, v, true)) void pushThpaste(site, v);
      }, 1500);
    });

    box.querySelectorAll('[data-act]').forEach((btn) => {
      ((btn as HTMLElement).onclick = async () => {
        const act = (btn as HTMLElement).dataset.act;
        if (act === 'import') {
          fileInput.click();
          return;
        }
        if (act === 'export') {
          const v = area.value || localStorage.getItem(cfg.store) || '';
          if (!v) {
            toast('Nothing to export', true);
            return;
          }
          const blob = new Blob([v], { type: 'text/plain' });
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = cfg.file;
          a.click();
          URL.revokeObjectURL(a.href);
          toast(`Exported ${cfg.file}`);
          return;
        }
        if (act === 'save') {
          const v = area.value.trim();
          if (storeCookies(cfg, v)) {
            toast(`${cfg.label} cookies saved in browser`);
            await pushThpaste(site, v);
          }
          return;
        }
        if (act === 'server') {
          const v = area.value.trim();
          if (!v) {
            toast('Paste cookies first', true);
            return;
          }
          const r = await api.saveCookies(site, v);
          if (r.success) {
            toast(`${cfg.label} server session saved`);
            const el = root.querySelector(`#${PREFIX}-status-${site}`);
            if (el) {
              el.classList.add('ok');
              el.textContent = 'Server session active.';
            }
            const dot = root.querySelector(`#${PREFIX}-dot-${site}`);
            if (dot) dot.classList.add('ok');
          } else toast(r.error || 'Save failed', true);
          return;
        }
        if (act === 'clear') {
          localStorage.removeItem(cfg.store);
          await api.clearCookies(site).catch(() => undefined);
          area.value = '';
          tpStatus(site, '');
          toast(`${cfg.label} cookies cleared`);
          return;
        }
        if (act === 'pull') {
          await pullThpaste(site);
          return;
        }
        if (act === 'push') {
          const v = area.value.trim() || localStorage.getItem(cfg.store) || '';
          if (!v) {
            toast('Nothing to push', true);
            return;
          }
          if (!v.includes('etoken')) {
            toast('No etoken found', true);
            return;
          }
          if (await pushThpaste(site, v)) toast(`${cfg.label} pushed to Thpaste`);
          return;
        }
      });
    });
    fileInput.onchange = (e) => {
      const f = (e.target as HTMLInputElement).files?.[0];
      if (!f) return;
      const rd = new FileReader();
      rd.onload = () => {
        area.value = String(rd.result || '');
        const v = area.value.trim();
        if (storeCookies(cfg, v, true)) {
          toast('File loaded & stored — tap Server to persist');
          void pushThpaste(site, v);
        } else {
          toast('File loaded — review & save');
        }
      };
      rd.readAsText(f);
    };
  });
}

function refreshServerStatus(root: ParentNode): void {
  api
    .cookieStatus()
    .then((r) => {
      for (const s of COOKIE_SITES) {
        const st = (r && r[s.site]) || null;
        const dot = root.querySelector(`#${PREFIX}-dot-${s.site}`);
        const el = root.querySelector(`#${PREFIX}-status-${s.site}`);
        if (!dot || !el) continue;
        if (!st || !st.configured) {
          el.textContent = 'No server session saved.';
          continue;
        }
        dot.classList.add('ok');
        el.classList.add('ok');
        const exp = st.expiry
          ? `expiry ${st.expiry.date}${st.expiry.expired ? ' (EXPIRED)' : ''}`
          : 'no expiry parsed';
        const acc = st.account
          ? ` · ${st.account.email} · ${st.account.total_ppm} min`
          : st.account_error
            ? ' · account lookup failed'
            : '';
        el.textContent = `Server session active — ${exp}${acc}`;
      }
    })
    .catch(() => {
      for (const s of COOKIE_SITES) {
        const el = root.querySelector(`#${PREFIX}-status-${s.site}`);
        if (el) el.textContent = 'Could not reach server.';
      }
    });
}

// Auto-load: fill any empty box from its Thpaste paste (never overwrites
// cookies already stored in this browser).
async function autoPull(): Promise<void> {
  let status: Awaited<ReturnType<typeof api.thpasteStatus>> | null = null;
  try {
    status = await api.thpasteStatus();
  } catch {
    return;
  }
  for (const s of COOKIE_SITES) {
    const area = document.querySelector(`#${PREFIX}-area-${s.site}`) as HTMLTextAreaElement | null;
    const hasLocal = (area && area.value.trim()) || localStorage.getItem(s.store);
    if (hasLocal) continue;
    const st = status[s.site];
    if (!st || !st.configured || st.error) continue;
    const content = (st.content || '').trim();
    if (!content.includes('etoken')) continue;
    if (area) area.value = content;
    storeCookies(s, content, true);
    tpStatus(s.site, 'auto-loaded from Thpaste', 'ok');
  }
}

function fillSiteBox(site: Site, text: string): void {
  const cfg = COOKIE_SITES.find((x) => x.site === site);
  if (!cfg) return;
  const area = document.querySelector(`#${PREFIX}-area-${site}`) as HTMLTextAreaElement | null;
  if (area) area.value = text;
  storeCookies(cfg, text.trim(), true);
  void pushThpaste(site, text.trim());
}

async function importAllToThpaste(): Promise<void> {
  const server = await api.thpasteImport().catch(() => null);
  let ok = 0;
  let fail = 0;
  let skipped = 0;
  for (const s of COOKIE_SITES) {
    const area = document.querySelector(`#${PREFIX}-area-${s.site}`) as HTMLTextAreaElement | null;
    const local = ((area && area.value.trim()) || localStorage.getItem(s.store) || '').trim();
    if (local.includes('etoken')) {
      if (await pushThpaste(s.site, local)) ok++;
      else fail++;
      continue;
    }
    const st = server?.results?.[s.site];
    if (st?.success) {
      ok++;
      setPasteLink(s.site, st.url || st.custom_url || st.raw_url);
      tpStatus(s.site, 'imported server cookies', 'ok');
    } else if (st?.skipped) {
      skipped++;
    } else if (st) {
      fail++;
      tpStatus(s.site, st.error || 'import failed', 'err');
    }
  }
  if (ok) toast(`Thpaste import complete — ${ok} paste${ok > 1 ? 's' : ''} ready`);
  else toast(!fail && skipped ? 'No cookies to import' : 'Thpaste import failed', true);
}

function exportAll(): void {
  const data: Record<string, string> = { version: '1', exported_at: new Date().toISOString(), ade: '', ea: '', dvd: '' };
  for (const s of COOKIE_SITES) {
    const area = document.querySelector(`#${PREFIX}-area-${s.site}`) as HTMLTextAreaElement | null;
    data[s.site] = (area && area.value.trim()) || localStorage.getItem(s.store) || '';
  }
  if (!data.ade && !data.ea && !data.dvd) {
    toast('Nothing to export', true);
    return;
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'all-cookies.json';
  a.click();
  URL.revokeObjectURL(a.href);
  toast('Exported all-cookies.json');
}

function importAll(e: Event): void {
  const input = e.target as HTMLInputElement;
  const f = input.files?.[0];
  input.value = '';
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    const text = String(rd.result || '');
    try {
      const obj = JSON.parse(text) as Record<string, unknown>;
      if (obj && (typeof obj.ade === 'string' || typeof obj.ea === 'string' || typeof obj.dvd === 'string')) {
        let n = 0;
        for (const s of COOKIE_SITES) {
          const v = obj[s.site];
          if (typeof v === 'string' && v.includes('etoken')) {
            fillSiteBox(s.site, v);
            n++;
          }
        }
        toast(n ? `Imported ${n} site${n > 1 ? 's' : ''} — tap Server to persist` : 'No valid cookies in file', !n);
        return;
      }
    } catch {
      /* not JSON — fall through to Netscape handling */
    }
    const lines = text.split(/\r?\n/);
    const header = lines.filter((l) => l.trim().startsWith('#'));
    const buckets: Record<Site, string[]> = { ade: [], ea: [], dvd: [] };
    for (const line of lines) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const host = t.split(/[\t ]+/)[0].toLowerCase();
      if (host.includes('elegantangel')) buckets.ea.push(line);
      else if (host.includes('dvderotik')) buckets.dvd.push(line);
      else buckets.ade.push(line);
    }
    let n = 0;
    for (const s of COOKIE_SITES) {
      if (!buckets[s.site].length) continue;
      const combined = [...header, ...buckets[s.site]].join('\n');
      if (!combined.includes('etoken')) continue;
      fillSiteBox(s.site, combined);
      n++;
    }
    toast(n ? `Imported ${n} site${n > 1 ? 's' : ''} — tap Server to persist` : 'No valid cookies in file', !n);
  };
  rd.readAsText(f);
}

export function renderCookiesPage(root: HTMLElement): void {
  if (!built) {
    root.innerHTML = `
      <div class="section-label">Cookies — paste once, stored automatically</div>
      <div class="cookie-page">
        <div class="modal-actions" style="justify-content:flex-start;margin:0 12px 12px 12px;">
          <button class="btn" id="pgExportAll">Export all</button>
          <button class="btn" id="pgImportAll">Import all</button>
          <button class="btn primary" id="pgThpasteImportAll">Push all → Thpaste</button>
          <input type="file" id="pgImportFile" accept=".json,.txt,.cookies" style="display:none" />
        </div>
        ${boxesHTML()}
      </div>`;
    wireBoxes(root);
    ($('pgExportAll') as HTMLElement).onclick = exportAll;
    ($('pgImportAll') as HTMLElement).onclick = () => ($('pgImportFile') as HTMLInputElement).click();
    ($('pgImportFile') as HTMLInputElement).onchange = importAll;
    ($('pgThpasteImportAll') as HTMLElement).onclick = () => void importAllToThpaste();
    built = true;
  } else {
    for (const s of COOKIE_SITES) {
      const area = root.querySelector(`#${PREFIX}-area-${s.site}`) as HTMLTextAreaElement | null;
      if (area && !area.value) area.value = localStorage.getItem(s.store) || '';
    }
  }
  refreshServerStatus(root);
  void autoPull();
}
