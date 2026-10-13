"""
대형 상업 화랑 화이트리스트 전시정보 수집기 (주 1회 실행 권장)

실행 위치: docs/ 디렉터리 안에서 실행한다. galleries.json을 같은 위치에서 읽는다.

  cd docs/
  uv pip install requests beautifulsoup4 anthropic
  export ANTHROPIC_API_KEY=...
  python crawl_galleries.py            # 수집 → out/exhibitions_YYYY-MM-DD.csv
  python crawl_galleries.py --audit    # robots/sitemap/RSS 점검만 → out/audit.json
  python crawl_galleries.py --only kukje,pkm  # 특정 갤러리만

관련 스크립트
  list_exhibition_venues.py  서울시 공공 API(culturalEventInfo)에서 전시/미술 행사를
                             장소별로 집계한다. SEOUL_API_KEY가 필요하며 이 스크립트와
                             독립적으로 실행한다.

원칙
  - robots.txt가 막은 URL은 요청하지 않는다.
  - 도메인당 요청 간격 REQUEST_DELAY초 이상.
  - 사실 정보(전시명, 작가, 기간, 지점, 원문 URL)만 저장. 본문·이미지는 저장하지 않는다.
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "SeoulExhibitionBot/0.1 (+mailto:you@example.com)"  # 연락처를 실제 주소로 바꿀 것
REQUEST_DELAY = 10  # 초
LLM_MODEL = "claude-haiku-4-5-20251001"
OUT_DIR = Path("out")

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT
_last_hit: dict[str, float] = {}
_robots: dict[str, robotparser.RobotFileParser] = {}


# ---------- 예의 바른 요청 ----------
def allowed(url: str) -> bool:
    host = urlparse(url)
    base = f"{host.scheme}://{host.netloc}"
    if base not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = session.get(base + "/robots.txt", timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])  # robots를 못 읽으면 허용으로 간주하되 audit에 기록
        _robots[base] = rp
    return _robots[base].can_fetch(USER_AGENT, url)


def polite_get(url: str) -> requests.Response | None:
    if not allowed(url):
        print(f"  [robots 차단] {url}")
        return None
    host = urlparse(url).netloc
    wait = REQUEST_DELAY - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    try:
        r = session.get(url, timeout=30)
    except requests.RequestException as e:
        print(f"  [요청 실패] {url}: {e}")
        return None
    if r.status_code != 200:
        print(f"  [HTTP {r.status_code}] {url}")
        return None
    # 가나아트처럼 EUC-KR인 사이트 대응
    if r.encoding is None or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r


# ---------- 1단계: RSS / sitemap 탐색 ----------
FEED_CANDIDATES = ["/feed", "/rss", "/rss.xml", "/blogs/exhibitions.atom", "/exhibitions/feed"]


def discover(g: dict) -> dict:
    base = "{0.scheme}://{0.netloc}".format(urlparse(g["list_url"]))
    found = {"feeds": [], "sitemap_exhibition_urls": []}
    for path in FEED_CANDIDATES:
        r = polite_get(base + path)
        if r is not None and ("<rss" in r.text[:500] or "<feed" in r.text[:500]):
            found["feeds"].append(base + path)
    sm = g.get("sitemap") or base + "/sitemap.xml"
    r = polite_get(sm)
    if r is not None:
        locs = re.findall(r"<loc>(.*?)</loc>", r.text)
        found["sitemap_exhibition_urls"] = [u for u in locs if "exhibition" in u.lower()][:200]
    return found


# ---------- 3단계: HTML → 텍스트 → LLM 추출 ----------
def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "footer"]):
        tag.decompose()
    text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n"))
    return text[:20000]


EXTRACT_PROMPT = """아래는 갤러리 '{name}'의 전시 목록 페이지 텍스트다.
오늘은 {today}이다. 서울 지점에서 '진행 중'이거나 '예정'인 전시만 JSON 배열로 추출하라.
서울 지점 표기 힌트: {seoul_label}
각 항목: {{"title": str, "artists": [str], "start_date": "YYYY-MM-DD"|null,
"end_date": "YYYY-MM-DD"|null, "branch": str|null, "detail_url": str|null}}
- 페이지에 없는 값은 지어내지 말고 null.
- 아트페어 부스, 해외 기관전, 다른 도시 지점 전시는 제외.
- 연도가 생략된 날짜는 문맥상 가장 가까운 연도로.
JSON 배열만 출력하라.

{text}"""


def llm_extract(g: dict, text: str) -> list[dict]:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=LLM_MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": EXTRACT_PROMPT.format(
            name=g["name"], today=date.today().isoformat(),
            seoul_label=g.get("seoul_label") or "(서울 단일 지점이거나 불명)", text=text)}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("  [LLM 응답 파싱 실패]")
        return []


# ---------- 검증 / 정규화 ----------
def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None


def validate(g: dict, items: list[dict], source_url: str) -> list[dict]:
    today = date.today()
    rows = []
    for it in items:
        start, end = parse_date(it.get("start_date")), parse_date(it.get("end_date"))
        problems = []
        if not it.get("title"):
            problems.append("제목없음")
        if end is None:
            problems.append("종료일없음")
        elif end < today:
            continue  # 끝난 전시 (캐시·지연 갱신된 페이지 대응)
        if start and end and start > end:
            problems.append("기간역전")
        rows.append({
            "gallery_id": g["id"], "gallery": g["name"],
            "branch": it.get("branch") or "",
            "title": (it.get("title") or "").strip(),
            "artists": "; ".join(a.strip() for a in it.get("artists") or []),
            "start_date": start.isoformat() if start else "",
            "end_date": end.isoformat() if end else "",
            "source_url": urljoin(source_url, it.get("detail_url") or "") or source_url,
            "fetched_at": today.isoformat(),
            "needs_review": ",".join(problems),
        })
    return rows


def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        key = (r["gallery_id"], re.sub(r"\W", "", r["title"].lower()), r["start_date"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ---------- 실행 ----------
FIELDS = ["gallery_id", "gallery", "branch", "title", "artists", "start_date",
          "end_date", "source_url", "fetched_at", "needs_review"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).parent / "galleries.json"))
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--only", help="쉼표로 구분한 gallery id")
    args = ap.parse_args()

    galleries = json.loads(Path(args.config).read_text(encoding="utf-8"))["galleries"]
    if args.only:
        ids = set(args.only.split(","))
        galleries = [g for g in galleries if g["id"] in ids]
    OUT_DIR.mkdir(exist_ok=True)

    if args.audit:
        report = {}
        for g in galleries:
            if not g.get("list_url"):
                continue
            print(f"[audit] {g['name']}")
            report[g["id"]] = {"robots_allows_list": allowed(g["list_url"]), **discover(g)}
        (OUT_DIR / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("→ out/audit.json")
        return

    all_rows = []
    for g in galleries:
        if g.get("status") == "manual" or not g.get("list_url"):
            print(f"[건너뜀] {g['name']} ({g.get('note', '')[:40]}…)")
            continue
        print(f"[수집] {g['name']}")
        r = polite_get(g["list_url"])
        if r is None:
            continue
        items = llm_extract(g, page_text(r.text))
        rows = validate(g, items, g["list_url"])
        print(f"  → {len(rows)}건")
        all_rows += rows

    all_rows = dedupe(all_rows)
    stamp = date.today().isoformat()
    path = OUT_DIR / f"exhibitions_{stamp}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(all_rows)

    # 지난 실행과 비교해 신규 전시만 따로 표시
    prev = sorted(OUT_DIR.glob("exhibitions_*.csv"))[:-1]
    if prev:
        with open(prev[-1], encoding="utf-8-sig") as f:
            old = {(r["gallery_id"], r["title"]) for r in csv.DictReader(f)}
        new = [r for r in all_rows if (r["gallery_id"], r["title"]) not in old]
        print(f"신규 전시 {len(new)}건")
    print(f"총 {len(all_rows)}건 → {path}")


if __name__ == "__main__":
    sys.exit(main())
