// ─── Shared UI helpers ────────────────────────────────────────────

export function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing #${id}`);
  return el;
}

export function esc(s: unknown): string {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export function toast(msg: string, err = false): void {
  $('toastText').textContent = msg;
  $('toast').classList.toggle('err', err);
  $('toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.remove('show'), 2200);
}

export async function copyText(t: string, label = 'Copied'): Promise<void> {
  try {
    await navigator.clipboard.writeText(t);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = t;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
  toast(label);
}

export function fmtRes(rs?: number[]): string {
  if (!rs || !rs.length) return 'N/A';
  const s = [...rs].sort((a, b) => a - b);
  return s.length > 2 ? `${s[0]}p – ${s[s.length - 1]}p` : s.map((r) => r + 'p').join(', ');
}
