// ─── In-site fullscreen image viewer ────────────────────────────────

import { $ } from './ui';
import { copyText } from './ui';

export interface ViewItem {
  thumb: string;
  full: string;
}

let items: ViewItem[] = [];
let index = 0;
let overlay: HTMLElement | null = null;

export function isViewerOpen(): boolean {
  return overlay !== null;
}

export function openViewer(list: ViewItem[], start: number): void {
  closeViewer();
  items = list;
  index = Math.max(0, Math.min(start, list.length - 1));

  overlay = document.createElement('div');
  overlay.className = 'viewer-overlay';
  overlay.innerHTML = `
    <div class="viewer-top">
      <span class="viewer-count" id="viewerCount"></span>
      <span class="viewer-actions">
        <button class="viewer-btn" id="viewerCopy" title="Copy image URL">Copy URL</button>
        <button class="viewer-btn" id="viewerClose" title="Close (Esc)">✕</button>
      </span>
    </div>
    <button class="viewer-arrow prev" id="viewerPrev" title="Previous (←)">‹</button>
    <div class="viewer-stage"><img id="viewerImg" alt="" /></div>
    <button class="viewer-arrow next" id="viewerNext" title="Next (→)">›</button>`;
  document.body.appendChild(overlay);

  ($('viewerClose') as HTMLElement).onclick = () => closeViewer();
  ($('viewerCopy') as HTMLElement).onclick = () =>
    void copyText(items[index].full, 'Copied image URL');
  ($('viewerPrev') as HTMLElement).onclick = (e) => {
    e.stopPropagation();
    step(-1);
  };
  ($('viewerNext') as HTMLElement).onclick = (e) => {
    e.stopPropagation();
    step(1);
  };
  overlay.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).classList.contains('viewer-overlay')) closeViewer();
  });

  // Swipe support
  let touchX: number | null = null;
  overlay.addEventListener('touchstart', (e) => {
    touchX = e.touches[0].clientX;
  });
  overlay.addEventListener('touchend', (e) => {
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 40) step(dx < 0 ? 1 : -1);
    touchX = null;
  });

  paint();
}

function paint(): void {
  if (!overlay || !items.length) return;
  const img = $('viewerImg') as HTMLImageElement;
  img.classList.add('loading');
  img.onload = () => img.classList.remove('loading');
  img.src = items[index].full;
  $('viewerCount').textContent = `${index + 1} / ${items.length}`;
  // Preload neighbours
  for (const d of [-1, 1]) {
    const n = items[(index + d + items.length) % items.length];
    if (n) {
      const pre = new Image();
      pre.src = n.full;
    }
  }
}

export function step(d: 1 | -1): void {
  if (!overlay || !items.length) return;
  index = (index + d + items.length) % items.length;
  paint();
}

export function copyCurrent(): void {
  if (overlay && items[index]) void copyText(items[index].full, 'Copied image URL');
}

export function closeViewer(): void {
  if (overlay) {
    overlay.remove();
    overlay = null;
    items = [];
  }
}
