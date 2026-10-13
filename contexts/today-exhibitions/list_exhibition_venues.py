"""
서울시 문화행사 정보(culturalEventInfo)에서 '전시/미술' 행사를 전부 받아
어떤 미술관·박물관·갤러리가 들어오는지 장소별로 집계한다.

사용법:
    pip install requests
    SEOUL_API_KEY=발급받은키 python list_exhibition_venues.py
결과: venues.csv (장소, 기관명, 분류, 행사수, 자치구, 최근 전시명)
"""
import csv
import os
from collections import defaultdict

import requests

KEY = os.environ["SEOUL_API_KEY"]
BASE = "http://openapi.seoul.go.kr:8088/{key}/json/culturalEventInfo/{s}/{e}/{cat}"
CATEGORY = "전시/미술"  # CODENAME 필터
PAGE = 1000  # 1회 최대 1000건


def fetch_all():
    rows, start = [], 1
    while True:
        url = BASE.format(key=KEY, s=start, e=start + PAGE - 1, cat=CATEGORY)
        data = requests.get(url, timeout=30).json().get("culturalEventInfo")
        if not data or data["RESULT"]["CODE"] != "INFO-000":
            break
        rows += data["row"]
        if start + PAGE > data["list_total_count"]:
            break
        start += PAGE
    return rows


def classify(name: str) -> str:
    """장소/기관명 키워드 기반의 거친 분류. 결과는 반드시 눈으로 검수할 것."""
    n = name.replace(" ", "")
    if "서울시립" in n or "SeMA" in name or "백남준" in n:
        return "서울시립미술관"
    if n.startswith("국립") or "국립" in n:
        return "국립"
    if any(k in n for k in ["구립", "문화재단", "구청", "서울공예박물관", "서울역사박물관",
                            "서울도서관", "세종문화회관", "DDP", "동대문디자인플라자"]):
        return "공공(구립·재단 등)"
    if "박물관" in n:
        return "박물관(공·사립 확인 필요)"
    if "미술관" in n:
        return "미술관(공·사립 확인 필요)"
    if any(k in n for k in ["갤러리", "Gallery", "gallery", "화랑", "아트스페이스", "스페이스"]):
        return "갤러리(사설 추정)"
    return "기타"


def main():
    rows = fetch_all()
    venues = defaultdict(lambda: {"count": 0, "org": set(), "gu": set(), "last": ""})
    for r in rows:
        place = (r.get("PLACE") or "").strip()
        v = venues[place]
        v["count"] += 1
        v["org"].add((r.get("ORG_NAME") or "").strip())
        v["gu"].add((r.get("GUNAME") or "").strip())
        v["last"] = r.get("TITLE", "")

    with open("venues.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["장소", "기관명", "분류", "행사수", "자치구", "전시명예시"])
        for place, v in sorted(venues.items(), key=lambda x: -x[1]["count"]):
            org = " / ".join(sorted(o for o in v["org"] if o))
            w.writerow([place, org, classify(place + " " + org), v["count"],
                        ",".join(sorted(g for g in v["gu"] if g)), v["last"]])

    print(f"전시/미술 행사 {len(rows)}건, 고유 장소 {len(venues)}곳 → venues.csv")


if __name__ == "__main__":
    main()
