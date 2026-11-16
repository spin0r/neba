// ─── In-site HLS playback (extracted m3u8 variants, played from the CDN) ──
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

export interface PlayVariant {
  height: number;   // 0 = unknown / auto
  url: string;      // media (or master) m3u8 URL
}

export interface PlaySource {
  variants: PlayVariant[];
  title?: string;
  pic?: string;     // thumbnail URL — shown immediately as a background while the player loads
}

let overlay: HTMLElement | null = null;
let player: DPlayerHandle | null = null;
let hls: Hls | null = null;
let escHandler: ((e: KeyboardEvent) => void) | null = null;
let dplayerPromise: Promise<void> | null = null;

// Playback state shared between DPlayer's customType hook and the quality buttons.
let videoEl: HTMLVideoElement | null = null;
let HlsLib: typeof Hls | null = null;
let variants: PlayVariant[] = [];
let activeIndex = -1;
let switchSeq = 0;
let openSeq = 0;
let qualityBtns: HTMLElement[] = [];

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

function qualityLabel(height: number): string {
  return height > 0 ? `${height}p` : 'Auto';
}

/** Prefer 720p, otherwise the best (list is sorted high → low by the backend). */
function pickDefault(list: PlayVariant[]): number {
  const exact = list.findIndex((v) => v.height === 720);
  return exact >= 0 ? exact : 0;
}

function paintQuality(): void {
  qualityBtns.forEach((btn, i) => btn.classList.toggle('active', i === activeIndex));
}

function play(video: HTMLVideoElement): void {
  void video.play().catch(() => undefined);
}

/**
 * Point the existing HLS pipeline at another variant without tearing the
 * player down. Keeps the playback position when switching quality.
 */
function switchTo(index: number): void {
  const variant = variants[index];
  if (!variant || index === activeIndex) return;

  activeIndex = index;
  paintQuality();

  const video = videoEl;
  if (!video) return; // player still loading; openPlay picks up the new index

  const resumeAt = Number.isFinite(video.currentTime) ? video.currentTime : 0;
  const seq = ++switchSeq;

  if (hls && HlsLib) {
    const lib = HlsLib;
    const onParsed = (): void => {
      hls?.off(lib.Events.MANIFEST_PARSED, onParsed);
      if (seq !== switchSeq) return;
      if (resumeAt > 0) {
        try {
          video.currentTime = resumeAt;
        } catch {
          // Some streams only expose a seekable window after loading a fragment.
        }
      }
      play(video);
    };
    hls.on(HlsLib.Events.MANIFEST_PARSED, onParsed);
    hls.loadSource(variant.url);
    return;
  }

  // Native HLS fallback (Safari/iOS).
  video.src = variant.url;
  const onMeta = (): void => {
    video.removeEventListener('loadedmetadata', onMeta);
    if (seq !== switchSeq) return;
    if (resumeAt > 0) {
      try {
        video.currentTime = resumeAt;
      } catch {
        // ignore
      }
    }
    play(video);
  };
  video.addEventListener('loadedmetadata', onMeta);
}

export function isPlayOpen(): boolean {
  return overlay !== null;
}

export async function openPlay(src: PlaySource): Promise<void> {
  closePlay();
  const seq = ++openSeq;

  variants = src.variants.filter((v) => !!v.url);
  if (!variants.length) return;
  activeIndex = pickDefault(variants);
  switchSeq = 0;

  overlay = document.createElement('div');
  overlay.className = 'play-overlay';
  overlay.tabIndex = -1;
  // If a thumbnail is available, set it as the overlay's background immediately
  // so there is no dark→bright flash when DPlayer initialises (~300ms later).
  if (src.pic) {
    const escaped = src.pic.replace(/"/g, '%22');
    overlay.style.cssText =
      `background-image: url("${escaped}"); ` +
      `background-size: contain; background-repeat: no-repeat; background-position: center;`;
  }

  const qualityHtml = variants
    .map(
      (v, i) =>
        `<button class="play-q${i === activeIndex ? ' active' : ''}" data-q="${i}" ` +
        `title="Play ${qualityLabel(v.height)}">${qualityLabel(v.height)}</button>`,
    )
    .join('');

  overlay.innerHTML = `
    <div class="play-top">
      <span class="play-title" id="playTitle"></span>
      <span class="play-actions">
        <span class="play-quality" id="playQuality">${qualityHtml}</span>
        <button class="viewer-btn" id="playClose" title="Close (Esc)">✕</button>
      </span>
    </div>
    <div class="play-player" id="playPlayer"></div>`;
  document.body.appendChild(overlay);
  // Take focus off the URL/login input so DPlayer's hotkeys (and not the
  // browser's default arrow scrolling) drive the video while it's open.
  overlay.focus({ preventScroll: true });

  const title = $('playTitle') as HTMLElement;
  const container = $('playPlayer') as HTMLElement;
  title.textContent = src.title || 'Stream player';

  qualityBtns = Array.from(overlay.querySelectorAll<HTMLElement>('.play-q'));
  qualityBtns.forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      switchTo(Number(btn.dataset.q));
    };
  });

  ($('playClose') as HTMLElement).onclick = () => closePlay();
  overlay.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).classList.contains('play-overlay')) closePlay();
  });
  escHandler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') closePlay();
  };
  document.addEventListener('keydown', escHandler);

  try {
    const [hlsModule] = await Promise.all([import('hls.js'), loadDPlayer()]);
    HlsLib = hlsModule.default;
  } catch {
    title.textContent = 'Could not load the player';
    return;
  }
  if (!overlay || seq !== openSeq) return; // closed/reopened while loading the player

  const DPlayerCtor = window.DPlayer;
  if (!DPlayerCtor) {
    title.textContent = 'Could not load the player';
    return;
  }
  const lib = HlsLib;
  if (!lib) {
    title.textContent = 'Could not load the player';
    return;
  }

  const selected = variants[activeIndex];

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
      url: selected.url,
      type: 'hls',
      customType: {
        hls: (video: HTMLVideoElement) => {
          videoEl = video;
          if (!lib.isSupported()) {
            // Safari/iOS: let the system play the m3u8 natively.
            video.src = selected.url;
            play(video);
            return;
          }
          const instance = new lib({
            maxBufferLength: 30,
            maxMaxBufferLength: 600,
            maxBufferSize: 60 * 1000 * 1000,
            maxBufferHole: 0.5,
            backBufferLength: 30,
            manifestLoadingTimeOut: 20000,
            fragLoadingTimeOut: 20000,
          });
          hls = instance;
          instance.loadSource(selected.url);
          instance.attachMedia(video);
          instance.on(lib.Events.MANIFEST_PARSED, () => {
            play(video);
          });
          instance.on(lib.Events.ERROR, (_evt, data) => {
            if (!data.fatal) return;
            if (data.type === lib.ErrorTypes.NETWORK_ERROR) instance.startLoad();
            else if (data.type === lib.ErrorTypes.MEDIA_ERROR) instance.recoverMediaError();
            else title.textContent = `Playback failed: ${data.details}`;
          });
        },
      },
    },
  });
}

export function closePlay(): void {
  openSeq++;
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
  videoEl = null;
  HlsLib = null;
  variants = [];
  activeIndex = -1;
  qualityBtns = [];
}
