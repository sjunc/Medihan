# 메디한 (Medihan)

진단서·소견서·건강검진 결과지 등 의료 서류를 올리면 개인정보를 자동으로 마스킹하고, 서류 내용과 의학 가이드라인(RAG) 근거를 바탕으로 쉽게 풀어서 설명해 주는 AI 의료 서류 해설 서비스입니다.

## 주요 기능

- **문서 전처리 & 개인정보 마스킹**: 의료 서류(이미지/PDF)를 EasyOCR로 인식하고 이름·주민등록번호·나이·연락처를 자동으로 가립니다. 마스킹 항목은 선택할 수 있습니다.
- **서류 기반 해설**: 정해진 템플릿에 값을 채우지 않습니다. OCR로 읽은 서류 원문을 기준으로 (1) 질병코드를 KCD-9 전체 표에서 정확 조회, (2) 병명·시술·검사 용어를 용어 사전에서 정확 조회, (3) 입·퇴원 기간 같은 날짜를 코드로 계산, (4) 서류 종류별 읽는 법과 판정기준을 RAG로 검색한 뒤, 이 결과를 근거로 LLM이 **서류에 실제로 적힌 항목만** 해설합니다. 서류에 없는 항목은 언급하지 않습니다.
- **검진 수치 판정**: 혈압, 공복혈당, 콜레스테롤 등을 국민건강보험공단 판정기준으로 평가합니다. 기준값은 코드가 아니라 `backend/app/data/nhis_criteria.json`에 있으며, 서류에 적힌 판정과 다르면 차이를 알려 줍니다.
- **근거 기반 답변 (RAG)**: `backend/knowledge_base/`의 문서를 ChromaDB에 인덱싱해 근거와 함께 답변합니다. 관련도가 낮은 검색 결과는 버립니다(`RAG_MIN_SCORE`). `04_kcd_disease_codes_sample.md`, `05_plain_language_terms_sample.md`, `06_medical_document_guide.md`는 **샘플**이며, 서비스 전에 KCD 원문·의학용어집으로 교체·확장해야 합니다. 사전형 항목은 `## 공식명 | 별칭, 별칭 | 코드` 제목줄 형식을 따라야 정확 조회되며, `- 쉬운 말:`, `- 진료과:` 같은 줄이 해설과 진료과 추천에 쓰입니다.
- **LangGraph 에이전트**: 요청 의도를 분류(버튼 → LLM 분류 → 키워드 순)하여 수치 판정 → 코드·용어·근거 조회 → 정책 검색 → 해설 → 병원 검색 → 리포트 생성 순으로 처리합니다.
- **공공 정책·병원 검색**: DuckDuckGo 웹 검색 결과만 사용합니다. 임의로 만든 병원·정책 정보는 없으며, 검색에 실패하면 실패했다고 안내합니다. 병원 검색에는 서류에서 도출된 진료과와 사용자가 입력한 지역이 필요합니다.
- **리포트 내보내기**: Word(.docx), PDF, 요약 카드 이미지(.png)로 저장합니다. 결과물은 `backend/generated_reports/`에 생성됩니다. 한글 폰트는 `MEDIHAN_FONT_PATH`로 지정할 수 있습니다.
- **OpenAI API 키**: 서류 해설에는 키가 필요합니다. 키가 없으면 해설을 지어내지 않고 코드·용어·판정 조회 결과와 마스킹된 인식 원문만 보여 줍니다. 웹 UI 상단에서 키를 입력할 수 있습니다.

## 기술 스택

| 구분 | 사용 기술 |
| --- | --- |
| Frontend | React 18, Vite 5, Tailwind CSS 4, lucide-react |
| Backend | FastAPI, Uvicorn, LangChain, LangGraph, ChromaDB |
| AI / OCR | OpenAI (기본 `gpt-4o-mini`), EasyOCR, OpenCV, PyMuPDF |
| 리포트 | python-docx, ReportLab, Pillow |

## 프로젝트 구조

```
medihan/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 엔트리포인트 (API 라우트)
│   │   ├── config.py          # 환경설정 기본값
│   │   ├── agent/             # LangGraph 워크플로우(graph.py), 도구(tools.py)
│   │   ├── services/          # OCR/마스킹, RAG, 코드·용어 조회, 판정 엔진, 리포트
│   │   └── data/              # KCD-9 코드표, 건강검진 판정기준(nhis_criteria.json)
│   ├── knowledge_base/        # 의학 근거 문서(.md) 및 ChromaDB 저장소
│   ├── generated_reports/     # 생성된 리포트 출력 폴더
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/                   # React 앱 (App.jsx 등)
    ├── vite.config.js         # /api 요청을 백엔드(8000)로 프록시
    └── package.json
```

## 사전 준비

- Python 3.12 (3.10 이상 권장)
- Node.js 18 이상, npm
- (선택) OpenAI API Key

## 실행 방법

백엔드와 프론트엔드를 각각 별도 터미널에서 실행합니다.

### 1. 백엔드 (포트 8000)

```bash
cd backend

# 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 의존성 설치 (EasyOCR 설치로 시간이 다소 걸립니다)
pip install -r requirements.txt

# 환경변수 설정 (선택)
cp .env.example .env
# .env 파일에 OPENAI_API_KEY 입력 (비워두면 AI 해설 불가)

# 서버 실행
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

서버가 시작되면 지식베이스가 자동으로 인덱싱됩니다. 첫 OCR 실행 시 EasyOCR 모델을 내려받으므로 인터넷 연결이 필요합니다.

- 상태 확인: http://127.0.0.1:8000/api/health
- API 문서(Swagger): http://127.0.0.1:8000/docs

### 2. 프론트엔드 (포트 5173)

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 http://localhost:5173 에 접속합니다.

### 프로덕션 빌드

```bash
cd frontend
npm run build      # dist/ 생성
npm run preview    # 빌드 결과 미리보기
```

## 환경 변수

`backend/.env`

| 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI API 키. 비워두면 AI 해설 불가, 웹 UI 상단에서도 설정 가능 | (빈 값) |
| `OPENAI_MODEL` | 사용할 OpenAI 모델 | `gpt-4o-mini` |
| `RAG_MIN_SCORE` | 이 점수 미만의 RAG 검색 결과는 제외 | `1.5` |
| `MEDIHAN_FONT_PATH` | 리포트·마스킹 이미지에 쓸 한글 폰트 경로 | OS 기본 폰트 탐색 |

## 주요 API

| Method | 경로 | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 서버 및 API 키 설정 상태 |
| POST | `/api/SetApiKey` | 런타임에 OpenAI API 키/모델 설정 |
| POST | `/api/preprocess` | 문서 업로드, OCR, 개인정보 마스킹, 수치 추출 |
| POST | `/api/chat` | LangGraph 에이전트 실행 (분석/요약/병원 추천/리포트) |
| POST | `/api/hospitals` | 진료과·지역 기반 병원 웹 검색 |
| POST | `/api/export` | 리포트(docx/pdf/png) 생성 |
| GET | `/api/download/{filename}` | 생성된 리포트 다운로드 |
| GET | `/api/rag/status` | RAG 인덱스 상태 |
| POST | `/api/rag/reindex` | RAG 인덱스 강제 재생성 |

## 참고 사항

- `knowledge_base/`에 `.md`, `.txt`, `.pdf` 문서를 추가한 뒤 `/api/rag/reindex`를 호출하면 근거 문서가 갱신됩니다.
- `knowledge_base/`의 문서와 `generated_reports/`의 리포트는 `.gitignore`로 저장소에서 제외됩니다(폴더는 `.gitkeep`으로 유지). 새 환경에서는 근거 문서를 직접 넣고 `/api/rag/reindex`를 호출하세요. KCD-9 상병마스터 xlsx를 `knowledge_base/`에 두고 `python scripts/build_kcd9_lookup.py`를 실행하면 `app/data/kcd9_codes.json`이 만들어집니다.
- `.env` 파일에는 API 키가 들어가므로 외부 저장소에 커밋하지 마세요.
- 본 서비스는 건강검진 결과 이해를 돕는 참고용이며, 의학적 진단·치료를 대체하지 않습니다. 정확한 판단은 의료진과 상담하세요.
