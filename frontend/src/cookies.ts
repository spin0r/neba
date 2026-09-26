// ─── Cookies page: per-site boxes, auto-store, PlainRaw sync ───────

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

function prStatus(site: Site, msg: string, cls = ''): void {
  const el = document.querySelector(`#${PREFIX}-pr-${site}`);
  if (el) {
    el.textContent = msg;
    el.className = 'pr-status' + (cls ? ' ' + cls : '');
  }
}

async function pushPlainRaw(site: Site, content: string): Promise<boolean> {
  prStatus(site, 'pushing…');
  const r = await api.plainrawPush(site, content).catch(() => null);
  if (r && r.success) {
    prStatus(site, 'PlainRaw updated', 'ok');
    return true;
  }
  prStatus(site, (r && r.error) || 'push failed', 'err');
  if (r && r.error && !r.error.includes('No PlainRaw paste configured')) toast(r.error, true);
  return false;
}

async function pullPlainRaw(site: Site): Promise<void> {
  const cfg = COOKIE_SITES.find((x) => x.site === site);
  if (!cfg) return;
  prStatus(site, 'pulling…');
  const r = await api.plainrawPull(site).catch(() => null);
  const st = r && r[site];
  if (!st || !st.configured) {
    prStatus(site, 'no PlainRaw paste configured', 'err');
    return;
  }
  if (st.error) {
    prStatus(site, st.error, 'err');
    return;
  }
  const content = (st.content || '').trim();
  if (!content.includes('etoken')) {
    prStatus(site, 'paste has no cookies', 'err');
    return;
  }
  const area = document.querySelector(`#${PREFIX}-area-${site}`) as HTMLTextAreaElement | null;
  if (area) area.value = content;
  storeCookies(cfg, content, true);
  prStatus(site, 'loaded from PlainRaw', 'ok');
  toast(`${cfg.label} loaded from PlainRaw`);
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
      <div class="pr-row">
        <button class="btn" data-act="pull">↓ PlainRaw</button>
        <button class="btn" data-act="push">↑ PlainRaw</button>
        <span class="pr-status" id="${PREFIX}-pr-${s.site}"></span>
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
        void pushPlainRaw(site, v);
      }, 50);
    });
    area.addEventListener('input', () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        const v = area.value.trim();
        if (v && v.includes('etoken') && storeCookies(cfg, v, true)) void pushPlainRaw(site, v);
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
            await pushPlainRaw(site, v);
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
          prStatus(site, '');
          toast(`${cfg.label} cookies cleared`);
          return;
        }
        if (act === 'pull') {
          await pullPlainRaw(site);
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
          if (await pushPlainRaw(site, v)) toast(`${cfg.label} pushed to PlainRaw`);
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
          void pushPlainRaw(site, v);
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

// Auto-load: fill any empty box from its PlainRaw paste (never overwrites
// cookies already stored in this browser).
async function autoPull(): Promise<void> {
  let status: Awaited<ReturnType<typeof api.plainrawStatus>> | null = null;
  try {
    status = await api.plainrawStatus();
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
    prStatus(s.site, 'auto-loaded from PlainRaw', 'ok');
  }
}

function fillSiteBox(site: Site, text: string): void {
  const cfg = COOKIE_SITES.find((x) => x.site === site);
  if (!cfg) return;
  const area = document.querySelector(`#${PREFIX}-area-${site}`) as HTMLTextAreaElement | null;
  if (area) area.value = text;
  storeCookies(cfg, text.trim(), true);
  void pushPlainRaw(site, text.trim());
}

function exportAll(): void {
  const data: Record<string, string> = { version: '1', exported_at: new Date().toISOString(), ade: '', ea: '' };
  for (const s of COOKIE_SITES) {
    const area = document.querySelector(`#${PREFIX}-area-${s.site}`) as HTMLTextAreaElement | null;
    data[s.site] = (area && area.value.trim()) || localStorage.getItem(s.store) || '';
  }
  if (!data.ade && !data.ea) {
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
      if (obj && (typeof obj.ade === 'string' || typeof obj.ea === 'string')) {
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
    const buckets: Record<Site, string[]> = { ade: [], ea: [] };
    for (const line of lines) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const host = t.split(/[\t ]+/)[0].toLowerCase();
      if (host.includes('elegantangel')) buckets.ea.push(line);
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
          <input type="file" id="pgImportFile" accept=".json,.txt,.cookies" style="display:none" />
        </div>
        ${boxesHTML()}
      </div>`;
    wireBoxes(root);
    ($('pgExportAll') as HTMLElement).onclick = exportAll;
    ($('pgImportAll') as HTMLElement).onclick = () => ($('pgImportFile') as HTMLInputElement).click();
    ($('pgImportFile') as HTMLInputElement).onchange = importAll;
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
