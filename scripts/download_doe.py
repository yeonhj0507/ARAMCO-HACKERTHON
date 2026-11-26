"""DOE LNG 수출 사업자 반기 보고서(Semi-Annual Report) PDF 일괄 다운로드.

  .venv\\Scripts\\python scripts\\download_doe.py                  # 2024~2026 업로드분 (기본)
  .venv\\Scripts\\python scripts\\download_doe.py --years 2025 2026
  .venv\\Scripts\\python scripts\\download_doe.py --all            # 2010년부터 전부 (약 1,100개, 680MB)
  .venv\\Scripts\\python scripts\\download_doe.py --dry-run        # 목록만 만들고 다운로드는 안 함

저장 위치: data/doe/<사업자>/<파일명>.pdf, 목록은 data/doe/manifest.csv
이미 받은 파일은 건너뛰므로 중간에 끊겨도 다시 실행하면 이어서 받는다.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin
from urllib.request import Request, urlopen

INDEX_URL = "https://www.energy.gov/hgeo/semi-annual-reporting-requirements-lng-exporters-2010-2026-dockets"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "doe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def get(url: str, tries: int = 6, timeout: int = 60) -> bytes:
    """서버가 동시 접속을 끊는 경우(TLS EOF)가 있어서 간격을 늘려가며 다시 시도한다."""
    for i in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(min(30, 2 ** (i + 1)))


class TableLinks(HTMLParser):
    """표(table) 안의 링크 (사업자 목록)."""

    def __init__(self):
        super().__init__()
        self.in_td = 0
        self.href = None
        self.text = ""
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.in_td += 1
        elif tag == "a" and self.in_td:
            self.href = dict(attrs).get("href")
            self.text = ""

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_td = max(0, self.in_td - 1)
        elif tag == "a" and self.href:
            self.links.append((self.text.strip(), self.href))
            self.href = None

    def handle_data(self, data):
        if self.href is not None:
            self.text += data


class AllLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            h = dict(attrs).get("href")
            if h:
                self.hrefs.append(h)


def upload_year(url: str) -> str:
    """파일 경로의 업로드 연도. /files/2025-10/... 또는 /files/2019/04/f61/..."""
    m = re.search(r"/files/(\d{4})[-/]\d{2}/", url)
    return m.group(1) if m else ""


def slug(s: str, n: int = 50) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:n]


def build_manifest() -> list[dict]:
    p = TableLinks()
    p.feed(get(INDEX_URL).decode("utf-8", "replace"))
    apps = {}
    for name, href in p.links:
        url = urljoin(INDEX_URL, href)
        if "energy.gov" in url and name:
            apps.setdefault(url, name)
    print(f"사업자 {len(apps)}곳 페이지 확인 중...", flush=True)

    rows, seen = [], set()

    def scan(item):
        url, name = item
        a = AllLinks()
        a.feed(get(url).decode("utf-8", "replace"))
        out = []
        for h in a.hrefs:
            full = urljoin(url, h)
            if re.search(r"\.pdf(\?|$)", full, re.I):
                out.append({"operator": name, "url": full.split("?")[0], "year": upload_year(full)})
        return out

    failed = []
    with ThreadPoolExecutor(3) as ex:
        futs = {ex.submit(scan, it): it for it in apps.items()}
        for fut in as_completed(futs):
            try:
                for r in fut.result():
                    if r["url"] not in seen:
                        seen.add(r["url"])
                        rows.append(r)
            except Exception as e:
                failed.append(futs[fut])
                print(f"  사업자 페이지 실패: {futs[fut][1]} ({e})")
    for url, name in failed:  # 실패한 사업자는 끝에 하나씩 천천히 다시
        time.sleep(5)
        try:
            for r in scan((url, name)):
                if r["url"] not in seen:
                    seen.add(r["url"])
                    rows.append(r)
            print(f"  재시도 성공: {name}")
        except Exception as e:
            print(f"  재시도 실패: {name} ({e}). 다시 실행하면 그 사업자만 이어서 받습니다.")
    for r in rows:
        fname = re.sub(r"[^A-Za-z0-9._()-]+", "_", unquote(r["url"].rsplit("/", 1)[-1]))
        r["path"] = str(Path(slug(r["operator"])) / fname)
    rows.sort(key=lambda r: (r["operator"], r["year"], r["path"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", default=["2024", "2025", "2026"])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    rows = build_manifest()
    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["operator", "year", "url", "path"])
        w.writeheader()
        w.writerows(rows)
    sel = rows if args.all else [r for r in rows if r["year"] in set(args.years)]
    print(f"전체 PDF {len(rows)}개 중 {len(sel)}개 대상 (목록: data/doe/manifest.csv)", flush=True)
    if args.dry_run:
        return

    todo = [r for r in sel if not (OUT / r["path"]).exists()]
    print(f"이미 받은 파일 {len(sel) - len(todo)}개 건너뜀, {len(todo)}개 다운로드 시작", flush=True)

    def fetch(r):
        dest = OUT / r["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = get(r["url"])
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return len(data)

    done, total, fails = 0, 0, []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch, r): r for r in todo}
        for fut in as_completed(futs):
            try:
                total += fut.result()
                done += 1
                if done % 20 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)}  ({total / 1e6:.0f} MB)", flush=True)
            except Exception as e:
                fails.append((futs[fut]["url"], str(e)))
    print(f"\n완료: {done}개, {total / 1e6:.0f} MB, 실패 {len(fails)}개")
    for u, e in fails[:10]:
        print("  실패:", u, e)
    if fails:
        print("실패한 파일은 다시 실행하면 그것만 받습니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
