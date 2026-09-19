# -*- coding: utf-8 -*-
"""성균관대 채용·모집 공지 크롤러 → data/jobs.json
공지 게시판 주소가 바뀌면 아래 BOARDS만 고치면 됩니다."""
import json, re, hashlib, datetime, pathlib
import requests
from bs4 import BeautifulSoup

BOARDS = [
    # (게시판 이름, 목록 URL)
    ("채용·모집", "https://www.skku.edu/skku/campus/skk_comm/notice05.do"),
    ("장학", "https://www.skku.edu/skku/campus/skk_comm/notice06.do"),
]
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "jobs.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (skku-jobs bot; +https://github.com)"}
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()

def norm_date(s):
    m = re.search(r"(20\d{2})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})", s)
    if not m: return None
    try: return datetime.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError: return None

def find_due(title):
    """제목에서 마감일 추출: ~9/25, ~09.25, 9월 25일까지, (~9.25.) 등"""
    pats = [
        r"[~∼]\s*(\d{1,2})\s*[./월]\s*(\d{1,2})",
        r"(\d{1,2})\s*[./월]\s*(\d{1,2})\s*일?\s*까지",
    ]
    for p in pats:
        m = re.search(p, title)
        if m:
            mo, d = int(m[1]), int(m[2])
            if 1 <= mo <= 12 and 1 <= d <= 31:
                year = TODAY.year
                try: due = datetime.date(year, mo, d)
                except ValueError: continue
                # 이미 한참 지난 날짜면 내년으로 해석 (12월에 1월 마감 공지 등)
                if (TODAY - due).days > 90: due = datetime.date(year + 1, mo, d)
                return due.isoformat(), m.group(0)
    return None, None

def crawl_board(name, url):
    items = []
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    seen = set()
    for a in soup.select("a[href*='articleNo']"):
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or len(title) < 6: continue
        href = a.get("href", "")
        m = re.search(r"articleNo=(\d+)", href)
        if not m: continue
        art = m.group(1)
        if art in seen: continue
        seen.add(art)
        link = href if href.startswith("http") else requests.compat.urljoin(url, href)
        # 같은 행(li/tr) 안에서 날짜·작성자 추측
        row = a.find_parent(["li", "tr"]) or a.parent
        row_text = row.get_text(" ", strip=True) if row else ""
        posted = norm_date(row_text) or TODAY.isoformat()
        due, due_text = find_due(title)
        item = {
            "id": hashlib.md5(f"{name}:{art}".encode()).hexdigest()[:12],
            "title": title, "url": link, "writer": name,
            "posted": posted,
        }
        if due: item["due"] = due; item["dueText"] = f"{due_text} 마감 추정"
        items.append(item)
    return items

def main():
    all_items, ok = [], False
    for name, url in BOARDS:
        try:
            got = crawl_board(name, url)
            all_items += got
            if got: ok = True
            print(f"[jobs] {name}: {len(got)}건")
        except Exception as e:
            print(f"[jobs] {name} 실패: {e}")
    if not ok and OUT.exists():
        print("[jobs] 새 데이터 없음 → 기존 파일 유지"); return
    all_items = all_items[:60]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "items": all_items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[jobs] 저장 완료: {len(all_items)}건")

if __name__ == "__main__":
    main()
