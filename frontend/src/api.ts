// ─── Typed API client ─────────────────────────────────────────────

export interface VariantLink {
  height: number;
  url: string;
}

export interface Screenshot {
  thumb: string;
  full: string;
}

export interface SceneInfo {
  n: number;
  performers: string[];
  title?: string;
  start_s?: number | null;
  end_s?: number | null;
}

export interface ScreenshotGroup {
  key: string;
  scene_id?: string | number | null;
  n: number;
  title: string;
  start_s?: number | null;
  end_s?: number | null;
  screenshots: Screenshot[];
}

export interface CapsProbe {
  prefix: string;
  gallery: string;
  master: string;
  start: number;
  end: number;
  step: number;
  count: number;
}

export interface ExtractData {
  site: string;
  studio?: string;
  title?: string;
  movie_title?: string;
  scene_title?: string;
  movie_id?: string | number | null;
  scene_id?: string | number | null;
  duration_s?: number | null;
  duration?: string;
  manifest_url?: string;
  base_stream_url?: string;
  resolutions?: number[];
  preferred_links?: VariantLink[];
  covers?: string[];
  screenshots?: Screenshot[];
  screenshot_groups?: ScreenshotGroup[];
  caps_probe?: CapsProbe | null;
  scene_thumb?: string | null;
  preview_url?: string | null;
  performers?: string[];
  scene_count?: number;
  scenes?: SceneInfo[];
  is_authorized?: boolean;
  cookies_source?: string;
  cookie_site?: string;
  source_url?: string;
}

export interface CookieExpiry {
  ts: number;
  date: string;
  expired: boolean;
  seconds_left: number;
}

export interface AccountInfo {
  email: string;
  total_ppm: number;
  mins: number;
  bonus_mins: number;
  membership: string;
}

export interface ThpasteInfo {
  configured: boolean;
  id?: string;
  title?: string;
  url?: string;
  raw_url?: string;
  custom_url?: string;
  content?: string;
  created_at?: string;
  error?: string;
}

export interface ThpastePushResult {
  success: boolean;
  id?: string;
  title?: string;
  url?: string;
  raw_url?: string;
  custom_url?: string;
  created_at?: string;
  error?: string;
  skipped?: boolean;
}

export interface SiteCookieStatus {
  configured: boolean;
  expiry?: CookieExpiry;
  account?: AccountInfo;
  account_error?: string;
  thpaste?: boolean;
  thpaste_url?: string;
  thpaste_raw_url?: string;
}

export type Site = 'ade' | 'ea' | 'dvd';

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new AuthError();
  if (!res.ok) throw new Error(res.statusText);
  return res.json() as Promise<T>;
}

export class AuthError extends Error {
  constructor() {
    super('locked');
  }
}

export const api = {
  authCheck: () => req<{ ok: boolean; locked: boolean }>('GET', '/api/auth-check'),
  login: (password: string) => req<{ success: boolean }>('POST', '/api/login', { password }),
  extract: (url: string, mode: string, cookies_ade: string, cookies_ea: string, cookies_dvd: string, cookies: string) =>
    req<{ success: boolean; data?: ExtractData; error?: string }>('POST', '/api/extract', {
      url, mode, cookies_ade, cookies_ea, cookies_dvd, cookies,
    }),
  cookieStatus: () => req<Record<Site, SiteCookieStatus>>('GET', '/api/cookies'),
  saveCookies: (site: Site, cookies: string) =>
    req<{ success: boolean; site?: Site; expiry?: CookieExpiry; error?: string }>('POST', '/api/cookies', { site, cookies }),
  clearCookies: (site: Site) =>
    req<{ success: boolean }>('DELETE', `/api/cookies?site=${site}`),
  thpasteStatus: () =>
    req<Record<Site, ThpasteInfo>>('GET', '/api/thpaste'),
  thpastePull: (site: Site) =>
    req<Record<Site, ThpasteInfo>>('GET', `/api/thpaste?site=${site}`),
  thpastePush: (site: Site, content: string) =>
    req<ThpastePushResult>('POST', '/api/thpaste', { site, content }),
  thpasteImport: () =>
    req<{ success: boolean; results: Record<Site, ThpastePushResult> }>('POST', '/api/thpaste/import'),
};
