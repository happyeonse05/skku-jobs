# skku-jobs — 담다 데이터 크롤러

담다 앱의 **마감함(채용·모집 공지)** 와 **봉룡학사 식단**을 매일 자동으로 가져오는 저장소입니다.

- `data/jobs.json` — 성균관대 채용·모집 공지
- `data/meals.json` — 봉룡학사 식단
- 매일 오전 6시·11시(KST)에 자동 실행되고, Actions 탭에서 수동 실행도 가능합니다.

## 주소가 바뀌었을 때
- 공지 게시판: `crawler/jobs.py` 맨 위 `BOARDS`
- 식단 페이지: `crawler/meals.py` 맨 위 `SOURCES`
