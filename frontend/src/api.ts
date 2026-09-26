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
  start_s?: number | null;
  end_s?: number | null;
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

export interface SiteCookieStatus {
  configured: boolean;
  expiry?: CookieExpiry;
  account?: AccountInfo;
  account_error?: string;
  plainraw?: boolean;
}

export type Site = 'ade' | 'ea';

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
  extract: (url: string, mode: string, cookies_ade: string, cookies_ea: string, cookies: string) =>
    req<{ success: boolean; data?: ExtractData; error?: string }>('POST', '/api/extract', {
      url, mode, cookies_ade, cookies_ea, cookies,
    }),
  cookieStatus: () => req<Record<Site, SiteCookieStatus>>('GET', '/api/cookies'),
  saveCookies: (site: Site, cookies: string) =>
    req<{ success: boolean; site?: Site; expiry?: CookieExpiry; error?: string }>('POST', '/api/cookies', { site, cookies }),
  clearCookies: (site: Site) =>
    req<{ success: boolean }>('DELETE', `/api/cookies?site=${site}`),
  plainrawStatus: () =>
    req<Record<Site, { configured: boolean; content?: string; updated_at?: string; error?: string }>>('GET', '/api/plainraw'),
  plainrawPull: (site: Site) =>
    req<Record<Site, { configured: boolean; content?: string; updated_at?: string; error?: string }>>(
      'GET', `/api/plainraw?site=${site}`,
    ),
  plainrawPush: (site: Site, content: string) =>
    req<{ success: boolean; updated_at?: string; error?: string }>('POST', '/api/plainraw', { site, content }),
};
