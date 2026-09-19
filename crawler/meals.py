# -*- coding: utf-8 -*-
"""봉룡학사(수원 자과캠 기숙사) 식단 크롤러 → data/meals.json
⚠️ 학교 사이트가 개편되면 아래 SOURCES의 주소만 바꿔 주세요.
   표(table)에서 날짜 헤더와 조식/중식/석식 행을 찾아내는 범용 방식이라
   대부분의 표 형태 식단 페이지에 그대로 동작합니다."""
import json, re, datetime, pathlib
import requests
from bs4 import BeautifulSoup

SOURCES = [
    # 후보 주소 — 위에서부터 차례로 시도해서 처음 성공하는 걸 씁니다.
    "https://dorm.skku.edu/dorm_suwon/menu_suwon/food_menu.jsp",
    "https://dorm.skku.edu/skku/menu/food_menu.jsp",
    "https://dorm.skku.edu/dorm_suwon/food/food_menu.jsp",
]
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "meals.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (skku-meals bot)"}
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()
MEAL_KEYS = {"조식": "breakfast", "아침": "breakfast", "중식": "lunch", "점심": "lunch", "석식": "dinner", "저녁": "dinner"}

def parse_date(text):
    m = re.search(r"(\d{1,2})\s*[./월]\s*(\d{1,2})", text)
    if not m: return None
    mo, d = int(m[1]), int(m[2])
    if not (1 <= mo <= 12 and 1 <= d <= 31): return None
    year = TODAY.year
    try: dt = datetime.date(year, mo, d)
    except ValueError: return None
    if (TODAY - dt).days > 180: dt = datetime.date(year + 1, mo, d)
    if (dt - TODAY).days > 180: dt = datetime.date(year - 1, mo, d)
    return dt.isoformat()

def split_menu(cell_text):
    parts = re.split(r"[\n,/·]|(?:\s{2,})", cell_text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) <= 30][:8]

def parse_tables(soup):
    days = {}
    for table in soup.find_all("table"):
        t = table.get_text(" ", strip=True)
        if not any(k in t for k in MEAL_KEYS): continue
        rows = table.find_all("tr")
        if not rows: continue
        # 날짜 헤더 행 찾기
        header_dates = []
        for row in rows[:3]:
            cells = row.find_all(["th", "td"])
            cand = [parse_date(c.get_text(" ", strip=True)) for c in cells]
            if sum(1 for x in cand if x) >= 2:
                header_dates = cand; break
        if not header_dates: continue
        for row in rows:
            cells = row.find_all(["th", "td"])
            if not cells: continue
            label = cells[0].get_text(" ", strip=True)
            meal = next((v for k, v in MEAL_KEYS.items() if k in label), None)
            if not meal: continue
            for idx, cell in enumerate(cells):
                if idx >= len(header_dates) or not header_dates[idx]: continue
                menu = split_menu(cell.get_text("\n", strip=True))
                if not menu: continue
                day = days.setdefault(header_dates[idx], {})
                day.setdefault(meal, menu)
    return days

def main():
    days = {}
    for url in SOURCES:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200: print(f"[meals] {url} → {r.status_code}"); continue
            r.encoding = r.apparent_encoding
            got = parse_tables(BeautifulSoup(r.text, "lxml"))
            if got:
                days = got; print(f"[meals] {url} 성공: {len(got)}일치"); break
            print(f"[meals] {url} 표는 있는데 식단을 못 읽음")
        except Exception as e:
            print(f"[meals] {url} 실패: {e}")
    if not days:
        if OUT.exists(): print("[meals] 새 데이터 없음 → 기존 파일 유지"); return
        print("[meals] 첫 실행인데 데이터 없음 → 빈 파일 생성")
    else:
        # 기존 데이터와 병합 (지난 날짜 지우고 새 날짜 덮어쓰기)
        try: prev = json.loads(OUT.read_text(encoding="utf-8")).get("days", {})
        except Exception: prev = {}
        keep = {k: v for k, v in prev.items() if k >= TODAY.isoformat()}
        keep.update(days); days = keep
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "days": days,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[meals] 저장 완료: {len(days)}일치")

if __name__ == "__main__":
    main()
