"""Probe caps CDN to find how many synth screenshot offsets actually resolve.

Usage:
    python3 check_caps_limit.py --master 4955723 --gallery 5723 --prefix p \
        --start 0 --end 9203 --step 10 [--workers 20]

Uses lightweight HEAD requests (falls back to ranged GET) and reports
existing vs missing offsets, so you can see the real ceiling instead of
the artificial synth limit (40 combined / 30 per scene).
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor


def build_url(prefix: str, gallery: str, master: str, offset: int) -> str:
    return (
        f"https://caps1cdn.adultempire.com/{prefix}/{gallery}/1280/"
        f"{master}_{offset:05d}_1280c.jpg"
    )


def check_one(session, url: str, timeout: int = 15) -> tuple[str, bool, str]:
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return url, True, "200"
        # CDN rejects HEAD (415 etc.) — confirm with a 1-byte ranged GET.
        g = session.get(url, headers={"Range": "bytes=0-0"},
                        timeout=timeout, stream=True)
        ok = g.status_code in (200, 206)
        try:
            g.close()
        except Exception:
            pass
        return url, ok, str(g.status_code)
    except Exception as e:  # noqa: BLE001
        return url, False, f"ERR {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", default="4955723")
    ap.add_argument("--gallery", default="5723")
    ap.add_argument("--prefix", default="p")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=9203)
    ap.add_argument("--step", type=int, default=10)
    ap.add_argument("--workers", type=int, default=20)
    a = ap.parse_args()

    try:
        from aebn_dl.ade_scraper import _get_session
        session = _get_session(None)
    except Exception:
        import requests
        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0"

    offsets = list(range(a.start, a.end + 1, a.step))
    urls = [build_url(a.prefix, a.gallery, a.master, o) for o in offsets]
    print(f"Probing {len(urls)} offsets "
          f"({a.start}..{a.end} step {a.step}) ...", flush=True)

    ok_urls: list[str] = []
    miss = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for url, ok, info in ex.map(lambda u: check_one(session, u), urls):
            if ok:
                ok_urls.append(url)
            else:
                miss += 1
                if miss <= 10:
                    print(f"  MISS {url} [{info}]")

    print(f"EXIST: {len(ok_urls)}/{len(urls)}  "
          f"MISSING: {len(urls) - len(ok_urls)}")
    if ok_urls:
        print(f"first: {ok_urls[0]}")
        print(f"last:  {ok_urls[-1]}")
    # Contiguous ceiling from start
    existing = {u for u in ok_urls}
    contiguous = 0
    for u in urls:
        if u in existing:
            contiguous += 1
        else:
            break
    print(f"contiguous-from-start: {contiguous} "
          f"(up to offset {(a.start + (contiguous - 1) * a.step) if contiguous else '-'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
