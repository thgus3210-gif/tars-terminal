# 배포 가이드 (실데이터로 띄우기)

TARS TERMINAL 백엔드를 GitHub에 올리고 인터넷에 배포하는 전체 절차입니다.
데모 웹사이트(게시형 HTML)는 이 과정이 **불필요**합니다 — 이 문서는 실시간
시세·CT.gov·SEC·AdisInsight를 붙인 실서비스를 띄울 때만 필요합니다.

---

## 1. GitHub 레포 만들고 올리기

```bash
cd tars-terminal            # 프로젝트 루트 (tars/ 폴더가 들어있는 곳)

git init
git add .
git commit -m "TARS TERMINAL backend"
git branch -M main
git remote add origin https://github.com/<your-account>/tars-terminal.git
git push -u origin main
```

`.gitignore`가 이미 `.env`, `*.db`, `universe_cache.json`을 제외합니다 —
**API 키와 로컬 DB는 절대 커밋되지 않습니다.**

디렉터리 구조는 이래야 합니다(레포 루트 기준):

```
tars-terminal/
├─ Dockerfile
├─ render.yaml
├─ Procfile
├─ .gitignore
├─ .env.example
└─ tars/
   ├─ app.py  auth.py  store.py  universe.py  universe_builder.py
   ├─ analytics.py  catalysts.py  daily_engine.py  pipeline_kb.py
   ├─ providers/  static/  requirements.txt
```

---

## 2. Render로 배포 (가장 쉬움, 추천)

1. https://render.com 가입 → GitHub 계정 연결.
2. **New → Blueprint** → 방금 올린 레포 선택. `render.yaml`을 자동 인식합니다.
3. 배포 후 **Environment** 탭에서 아래를 채웁니다:
   - `ALLOWED_ORIGINS` = `https://<your-app>.onrender.com` (배포되면 나오는 URL)
   - `FMP_API_KEY` = FMP 키 (실시간 시세용, 아래 4번). 비워두면 샘플 시세로 동작.
   - `QUOTE_PROVIDER` = 키를 넣었으면 `fmp`, 아니면 `sample`.
   - `SESSION_SECRET`는 Render가 자동 생성합니다.
4. 저장하면 자동 재배포. 이후 `git push`할 때마다 자동 배포됩니다.

Render 대신 **Railway/Fly.io**도 동일합니다: 레포 연결 → 환경변수 입력 →
시작 명령 `uvicorn tars.app:app --host 0.0.0.0 --port $PORT`.

> **디스크:** `render.yaml`이 `/app/tars`에 1GB 디스크를 붙여 `tars.db`(계정·
> 관심종목·노트)와 `universe_cache.json`을 영구 보존합니다. 이게 없으면 재배포
> 때 계정이 초기화됩니다.

---

## 3. VPS(직접 서버)로 배포 — 대안

```bash
git clone https://github.com/<your-account>/tars-terminal.git
cd tars-terminal
pip install -r tars/requirements.txt
cp .env.example .env && nano .env         # 키·시크릿 입력
python -m tars.universe_builder           # 유니버스 캐시 생성
uvicorn tars.app:app --host 0.0.0.0 --port 8000
```

앞단에 Caddy/Nginx로 HTTPS를 붙이거나, 빠르게는
`cloudflared tunnel --url http://localhost:8000`로 노출.

---

## 4. API 키 발급 (하이브리드: 무료 + 일부 유료)

| 용도 | 소스 | 키 |
|---|---|---|
| 유니버스(XBI/NBI) | SSGA, iShares | 불필요 |
| 임상·카탈리스트 | ClinicalTrials.gov v2 | 불필요 |
| 공시·CIK·8-K | SEC EDGAR | 불필요(User-Agent 권장) |
| 시세·재무·뉴스 | **FMP** 또는 Finnhub | 필요 → `FMP_API_KEY` |
| 파이프라인 온톨로지 | AdisInsight | 계약/키(어댑터 슬롯) |

FMP 무료 티어로 시작 가능하고, 한도가 부족하면 유료 전환. 키는 코드가 아니라
**호스팅 대시보드 환경변수**에만 넣습니다.

---

## 5. 유니버스 갱신 (XBI/NBI 리밸런싱 반영)

유니버스는 `universe_cache.json`에 캐시되며 7일 후 자동 재빌드됩니다. 즉시
갱신하려면:

```bash
python -m tars.universe_builder      # 로컬/서버에서
```

또는 관리자용으로 `/api/admin/refresh-universe` 같은 보호 엔드포인트를 추가해도
됩니다(원하면 만들어 드립니다). 현재 XBI 보유종목은 안정적으로 받아지고, IBB는
iShares 봇게이팅으로 간헐적이라 실패 시 XBI+curated로 정상 축소됩니다.

---

## 6. 프론트엔드 연결 2가지

- **(A) 같은 서버 서빙(권장):** `tars/static/`의 로그인·터미널 HTML을 백엔드가
  그대로 서빙하므로, 브라우저 fetch가 동일 오리진의 실 API를 호출합니다. CORS·
  쿠키세션 문제 없음. 게시형 데모 HTML을 이 `static/`에 얹으면 실데이터로 붙습니다.
- **(B) 분리 운영:** 게시형 데모는 그대로, 실서비스는 별도 도메인. 이때는
  `ALLOWED_ORIGINS`에 프론트 도메인을 넣어 CSRF/Origin 검사를 통과시킵니다.

---

## 배포 체크리스트

- [ ] `.env`가 커밋되지 않았는지 확인 (`git status`에 안 보여야 함)
- [ ] `SESSION_SECRET` 설정(자동생성 또는 `openssl rand -hex 32`)
- [ ] `SESSION_SECURE=1`, `ALLOWED_ORIGINS`=배포 URL
- [ ] 디스크 마운트로 DB/캐시 영구화
- [ ] 로그인 레이트리밋 추가(원하면 slowapi로 붙여드립니다)
- [ ] `QUOTE_PROVIDER`/`FMP_API_KEY`로 실시세 on/off
