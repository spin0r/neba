// ─── In-site HLS scene preview (720p, played straight from the CDN) ──
// Player: dplayer-enhanced (loaded from jsDelivr on demand).
// HLS: hls.js, attached ourselves through DPlayer's customType hook.
// No server fetch/proxy — the CDN sends Access-Control-Allow-Origin: *.

import type Hls from 'hls.js';
import { $ } from './ui';

const DPLAYER_CDN = 'https://cdn.jsdelivr.net/npm/dplayer-enhanced@beta/dist/';

interface DPlayerHandle {
  destroy(): void;
}

type DPlayerCtor = new (options: Record<string, unknown>) => DPlayerHandle;

declare global {
  interface Window {
    DPlayer?: DPlayerCtor;
  }
}

export interface PreviewSource {
  url: string;
  title?: string;
  pic?: string;   // thumbnail URL — shown immediately as a background while the player loads
}

let overlay: HTMLElement | null = null;
let player: DPlayerHandle | null = null;
let hls: Hls | null = null;
let escHandler: ((e: KeyboardEvent) => void) | null = null;
let dplayerPromise: Promise<void> | null = null;

function loadDPlayer(): Promise<void> {
  if (window.DPlayer) return Promise.resolve();
  if (dplayerPromise) return dplayerPromise;

  dplayerPromise = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-dplayer]')) {
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = `${DPLAYER_CDN}DPlayer.min.css`;
      css.dataset.dplayer = '1';
      document.head.appendChild(css);
    }
    const script = document.createElement('script');
    script.src = `${DPLAYER_CDN}DPlayer.min.js`;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      dplayerPromise = null;
      reject(new Error('Failed to load DPlayer'));
    };
    document.head.appendChild(script);
  });
  return dplayerPromise;
}

/** Pick the 720p level; fall back to the closest lower one, then the lowest. */
function pick720(levels: { height: number }[]): number {
  const exact = levels.findIndex((l) => l.height === 720);
  if (exact >= 0) return exact;

  const below = levels
    .map((l, i) => ({ h: l.height, i }))
    .filter((x) => x.h > 0 && x.h <= 720)
    .sort((a, b) => b.h - a.h)[0];
  if (below) return below.i;

  const above = levels
    .map((l, i) => ({ h: l.height, i }))
    .filter((x) => x.h > 0)
    .sort((a, b) => a.h - b.h)[0];
  return above ? above.i : -1;
}

export function isPreviewOpen(): boolean {
  return overlay !== null;
}

export async function openPreview(src: PreviewSource): Promise<void> {
  closePreview();

  overlay = document.createElement('div');
  overlay.className = 'preview-overlay';
  overlay.tabIndex = -1;
  // If a thumbnail is available, set it as the overlay's background immediately
  // so there is no dark→bright flash when DPlayer initialises (~300ms later).
  if (src.pic) {
    const escaped = src.pic.replace(/"/g, '%22');
    overlay.style.cssText =
      `background-image: url("${escaped}"); ` +
      `background-size: contain; background-repeat: no-repeat; background-position: center;`;
  }
  overlay.innerHTML = `
    <div class="preview-top">
      <span class="preview-title" id="previewTitle"></span>
      <span class="preview-actions">
        <span class="preview-badge" id="previewBadge">720p</span>
        <button class="viewer-btn" id="previewClose" title="Close (Esc)">✕</button>
      </span>
    </div>
    <div class="preview-player" id="previewPlayer"></div>`;
  document.body.appendChild(overlay);
  // Take focus off the URL/login input so DPlayer's hotkeys (and not the
  // browser's default arrow scrolling) drive the video while it's open.
  overlay.focus({ preventScroll: true });

  const title = $('previewTitle') as HTMLElement;
  const badge = $('previewBadge') as HTMLElement;
  const container = $('previewPlayer') as HTMLElement;
  title.textContent = src.title || 'Scene preview';

  ($('previewClose') as HTMLElement).onclick = () => closePreview();
  overlay.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).classList.contains('preview-overlay')) closePreview();
  });
  escHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') closePreview();
  };
  document.addEventListener('keydown', escHandler);

  let HlsLib: typeof Hls;
  try {
    const [hlsModule] = await Promise.all([import('hls.js'), loadDPlayer()]);
    HlsLib = hlsModule.default;
  } catch {
    title.textContent = 'Could not load the preview player';
    return;
  }
  if (!overlay) return; // closed while loading the player

  const DPlayerCtor = window.DPlayer;
  if (!DPlayerCtor) {
    title.textContent = 'Could not load the preview player';
    return;
  }

  // Attach hls.js through customType. Chrome now advertises native HLS
  // (canPlayType → "maybe"), and DPlayer would then feed the m3u8 straight
  // to the <video> element, which cannot demux this MPEG-TS stream.
  player = new DPlayerCtor({
    container,
    autoplay: true,
    hotkey: true,
    globalHotkey: true,
    theme: '#FFD93D',
    video: {
      url: src.url,
      type: 'hls',
      customType: {
        hls: (video: HTMLVideoElement) => {
          if (!HlsLib.isSupported()) {
            // Safari/iOS: let the system play the m3u8 natively.
            badge.textContent = 'auto';
            video.src = src.url;
            void video.play().catch(() => undefined);
            return;
          }
          const instance = new HlsLib({
            maxBufferLength: 30,
            maxMaxBufferLength: 600,
            maxBufferSize: 60 * 1000 * 1000,
            maxBufferHole: 0.5,
            backBufferLength: 30,
            manifestLoadingTimeOut: 20000,
            fragLoadingTimeOut: 20000,
          });
          hls = instance;
          instance.loadSource(src.url);
          instance.attachMedia(video);
          instance.on(HlsLib.Events.MANIFEST_PARSED, () => {
            const level = pick720(instance.levels);
            if (level >= 0) instance.currentLevel = level; // pin to 720p
            void video.play().catch(() => undefined);
          });
          instance.on(HlsLib.Events.LEVEL_SWITCHED, (_evt, data) => {
            const level = instance.levels[data.level];
            if (level?.height) badge.textContent = `${level.height}p`;
          });
          instance.on(HlsLib.Events.ERROR, (_evt, data) => {
            if (!data.fatal) return;
            if (data.type === HlsLib.ErrorTypes.NETWORK_ERROR) instance.startLoad();
            else if (data.type === HlsLib.ErrorTypes.MEDIA_ERROR) instance.recoverMediaError();
            else {
              badge.textContent = 'error';
              title.textContent = `Preview failed: ${data.details}`;
            }
          });
        },
      },
    },
  });
}

export function closePreview(): void {
  if (escHandler) {
    document.removeEventListener('keydown', escHandler);
    escHandler = null;
  }
  if (hls) {
    hls.destroy();
    hls = null;
  }
  if (player) {
    player.destroy();
    player = null;
  }
  if (overlay) {
    overlay.remove();
    overlay = null;
  }
}
