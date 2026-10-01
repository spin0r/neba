// ─── Boot, page router, login ───────────────────────────────────────

import './style.css';
import { api, AuthError } from './api';
import { $ } from './ui';
import { toast } from './ui';
import {
  renderHist,
  initExtractPage,
  showExtractChrome,
  hideExtractBodies,
  refreshExtractVisibility,
  fetchExtract,
  moveSelection,
  activateSelection,
  resetSelection,
  cycleMode,
} from './extract';
import { renderCookiesPage } from './cookies';
import { isViewerOpen, step as viewerStep, closeViewer, copyCurrent } from './viewer';

type Page = 'extract' | 'cookies';

let page: Page = 'extract';
let authed = true;

const resultBodyHidden = (): boolean => $('resultBody').innerHTML === '';

function showPage(next: Page): void {
  page = next;
  const onCookies = next === 'cookies';
  showExtractChrome(!onCookies);
  if (onCookies) {
    hideExtractBodies();
    renderCookiesPage($('cookiesPage'));
    $('cookiesPage').classList.add('visible');
    if (location.hash !== '#/cookies') history.replaceState(null, '', '#/cookies');
  } else {
    $('cookiesPage').classList.remove('visible');
    refreshExtractVisibility(authed);
    if (location.hash === '#/cookies') history.replaceState(null, '', location.pathname);
  }
}

window.addEventListener('hashchange', () => {
  showPage(location.hash === '#/cookies' ? 'cookies' : 'extract');
});

// ── Global paste: intercept clipboard pastes anywhere on the page ──
// If the pasted text contains a recognisable URL, auto-fill the input and start
// extraction immediately — no need to click the input first.
const SUPPORTED_URL_RE =
  /https?:\/\/[^\s]*(?:aebn\.com|m\.aebn\.net|adultdvdempire\.com|adultempire\.com|elegantangel\.com)[^\s]*/i;

document.addEventListener('paste', (e: ClipboardEvent) => {
  // Don't intercept pastes inside password fields or textareas
  const target = e.target as HTMLElement;
  if (
    target.tagName === 'TEXTAREA' ||
    (target.tagName === 'INPUT' && (target as HTMLInputElement).type === 'password')
  )
    return;
  // Ignore if a modal is open
  if (document.querySelector('.modal-overlay')) return;
  // Ignore if we're already on the cookies page
  if (page !== 'extract') return;

  const text = e.clipboardData?.getData('text') || '';
  const m = SUPPORTED_URL_RE.exec(text);
  if (!m) return;

  // Prevent the default paste into whatever was focused
  e.preventDefault();

  const url = m[0].replace(/[)\]}>'"]+$/, ''); // strip trailing punctuation
  const input = $('urlInput') as HTMLInputElement;
  input.value = url;

  // Visual flash to show the URL was captured
  input.classList.add('paste-flash');
  setTimeout(() => input.classList.remove('paste-flash'), 600);

  if (authed) {
    void fetchExtract();
  }
});

// ── Global keyboard: ↑/↓ navigate rows, Enter activates/copies ──
function resultsVisible(): boolean {
  return $('resultBody').classList.contains('visible') && $('resultBody').innerHTML !== '';
}

document.addEventListener('keydown', (e) => {
  const tag = (e.target as HTMLElement).tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (document.querySelector('.modal-overlay')) return;

  // Viewer takes over all keys while open
  if (isViewerOpen()) {
    if (e.key === 'ArrowRight') viewerStep(1);
    else if (e.key === 'ArrowLeft') viewerStep(-1);
    else if (e.key === 'Escape') closeViewer();
    else if (e.key === 'Enter') copyCurrent();
    else return;
    e.preventDefault();
    return;
  }

  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    if (!resultsVisible() || page !== 'extract') return;
    e.preventDefault();
    moveSelection(e.key === 'ArrowDown' ? 1 : -1);
  } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    if (page !== 'extract') return;
    e.preventDefault();
    cycleMode(e.key === 'ArrowRight' ? 1 : -1);
  } else if (e.key === 'Enter') {
    if (tag === 'INPUT' && (e.target as HTMLInputElement).id === 'urlInput') {
      // Enter in the URL bar: copy selection if navigating, else fetch
      if (resultsVisible() && activateSelection()) e.preventDefault();
      else void fetchExtract();
    } else if (tag !== 'INPUT' && tag !== 'BUTTON') {
      if (resultsVisible() && page === 'extract' && activateSelection()) e.preventDefault();
    }
  } else if (e.key === 'Escape') {
    resetSelection();
    document.querySelectorAll('.selected').forEach((el) => el.classList.remove('selected'));
  }
});

// ── Login ──
function showLogin(): void {
  authed = false;
  $('loginBody').classList.add('visible');
  hideExtractBodies();
  $('cookiesPage').classList.remove('visible');
}

async function doLogin(): Promise<void> {
  const r = await api.login(($('loginPass') as HTMLInputElement).value).catch(() => null);
  if (r && r.success) {
    authed = true;
    $('loginBody').classList.remove('visible');
    renderHist();
    if (page === 'cookies') showPage('cookies');
    else refreshExtractVisibility(true);
    toast('Unlocked');
  } else {
    toast('Wrong password', true);
  }
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  initExtractPage();
  renderHist();
  ($('loginBtn') as HTMLElement).onclick = () => void doLogin();
  ($('loginPass') as HTMLInputElement).addEventListener('keydown', (e) => {
    if (e.key === 'Enter') void doLogin();
  });
  window.addEventListener('ae:locked', () => showLogin());

  void (async () => {
    try {
      await api.authCheck();
      if (location.pathname === '/cookies' || location.hash === '#/cookies') showPage('cookies');
      else if (resultBodyHidden()) $('histBody').classList.add('visible');
    } catch (e) {
      if (e instanceof AuthError || e instanceof Error) showLogin();
    }
  })();
});
