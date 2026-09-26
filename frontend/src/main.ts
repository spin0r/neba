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
} from './extract';
import { renderCookiesPage } from './cookies';

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
