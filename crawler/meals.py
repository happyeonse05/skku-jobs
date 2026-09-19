# -*- coding: utf-8 -*-
"""봉룡학사 식단 크롤러 → data/meals.json
봉룡학사 공식 일별 식단 페이지에서 오늘부터 7일치를 가져옵니다.
페이지: dorm.skku.edu 주간 식단표 (board_no=61)"""
import json, re, datetime, pathlib, time
import requests
from bs4 import BeautifulSoup

MENU_URL = "https://dorm.skku.edu/_custom/skku/_common/board/schedule_menu/food_menu_page.jsp"
BOARD_NO = "61"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "meals.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (damda meals bot)"}
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).date()
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[~∼]\s*\d{1,2}:\d{2}")
VENUE_RE = re.compile(r"^(공통|신관|지관|인관|의관|예관|Take-?out.*)$", re.I)

def meal_of(hour):
    if hour < 10: return "breakfast"
    if hour < 15: return "lunch"
    return "dinner"

def clean_items(raw):
    out = []
    for p in re.split(r"[,\n]", raw):
        p = p.strip()
        if not p: continue
        if re.fullmatch(r"\*?[\d,]+원?\*?", p): continue   # *6,000* 가격 표기
        if VENUE_RE.match(p): continue                      # 장소 이름
        p = re.sub(r"\*[\d,]+\*", "", p).strip("*· ").strip()
        if p and len(p) <= 40: out.append(p)
    return out

def crawl_day(day):
    r = requests.get(MENU_URL, params={"date": day.isoformat(), "board_no": BOARD_NO, "lng": "ko"},
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    text = BeautifulSoup(r.text, "lxml").get_text("\n", strip=True)
    meals = {"breakfast": [], "lunch": [], "dinner": []}
    takeout = {"breakfast": [], "lunch": [], "dinner": []}
    for m in TIME_RE.finditer(text):
        meal = meal_of(int(m.group(1)))
        before = text[:m.start()].rstrip("\n ").rsplit("\n", 1)[-1]
        nxt = TIME_RE.search(text, m.end())
        chunk = text[m.end(): nxt.start() if nxt else len(text)]
        items = clean_items(chunk)
        (takeout if "take" in before.lower() else meals)[meal].extend(items)
    day_data = {}
    for k in ("breakfast", "lunch", "dinner"):
        merged = meals[k] or takeout[k]   # 정식 메뉴 우선, 없으면 테이크아웃
        seen, final = set(), []
        for it in merged:
            if it not in seen:
                seen.add(it); final.append(it)
        if final: day_data[k] = final[:8]
    return day_data

def main():
    days = {}
    # 이번 주 월요일부터 오늘+7일까지 수집 (주말에도 이번 주 식단 확보)
    start = TODAY - datetime.timedelta(days=TODAY.weekday())
    total = (TODAY + datetime.timedelta(days=7) - start).days + 1
    for i in range(total):
        d = start + datetime.timedelta(days=i)
        try:
            got = crawl_day(d)
            if got: days[d.isoformat()] = got
            print(f"[meals] {d}: {'OK ' + str(list(got.keys())) if got else '메뉴 없음'}")
            time.sleep(0.5)
        except Exception as e:
            print(f"[meals] {d} 실패: {e}")
    if not days and OUT.exists():
        print("[meals] 새 데이터 없음 → 기존 파일 유지"); return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.datetime.now(KST).isoformat(timespec="seconds"),
        "days": days,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[meals] 저장 완료: {len(days)}일치")

if __name__ == "__main__":
    main()
