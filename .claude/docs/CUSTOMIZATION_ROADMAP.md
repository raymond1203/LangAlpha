# CUSTOMIZATION_ROADMAP.md — 한국 시장 커스터마이징 로드맵

> 이 문서는 LangAlpha 포크의 한국 시장 확장 계획을 Phase별로 정리한다.
> 각 Phase는 독립적으로 완료·테스트 가능한 단위로 설계했다.

---

## Phase 1: pykrx 기반 한국 시장 MCP 서버 최소 구현

**목표**: KOSPI/KOSDAQ 종목의 OHLCV 시세 조회를 MCP 도구로 노출한다.

### 수정/추가 파일

| 작업 | 파일 | 종류 |
|------|------|------|
| pykrx MCP 서버 구현 | `mcp_servers/korean/kr_price_mcp_server.py` | **신규** |
| 패키지 초기화 | `mcp_servers/korean/__init__.py` | **신규** |
| 의존성 추가 | `pyproject.toml` | **수정** — `dependencies`에 `pykrx>=1.0.45` 추가 |
| MCP 서버 등록 | `agent_config.yaml` | **수정** — `mcp.servers`에 `kr_price` 항목 추가 |
| 단위 테스트 | `tests/unit/mcp_servers/korean/test_kr_price_mcp.py` | **신규** |

### kr_price_mcp_server.py 설계

```python
# FastMCP 패턴을 따름 (yf_price_mcp_server.py 참조)
from mcp.server.fastmcp import FastMCP
from pykrx import stock

mcp = FastMCP("KoreanPriceMCP")

@mcp.tool()
def get_kr_stock_history(ticker: str, from_date: str, to_date: str,
                         interval: str = "daily") -> dict:
    """KOSPI/KOSDAQ 종목의 OHLCV 히스토리를 조회한다."""
    # pykrx.stock.get_market_ohlcv_by_date()
    ...

@mcp.tool()
def get_kr_market_cap(ticker: str, from_date: str, to_date: str) -> dict:
    """종목의 시가총액·거래대금·상장주식수를 조회한다."""
    # pykrx.stock.get_market_cap_by_date()
    ...

@mcp.tool()
def search_kr_ticker(name: str) -> dict:
    """종목명으로 한국 주식 티커를 검색한다."""
    # pykrx.stock.get_market_ticker_and_name()
    ...
```

### agent_config.yaml 변경

```yaml
# FORK: 한국 시장 MCP 서버
- name: "kr_price"
  enabled: true
  command: "uv"
  args: ["run", "python", "mcp_servers/korean/kr_price_mcp_server.py"]
  env: {}
  tool_exposure_mode: "detailed"
```

### 테스트 전략

- **단위**: pykrx 응답을 mock하여 도구 함수의 입출력 검증
- **통합**: 실제 pykrx API 호출 (CI에서는 `@pytest.mark.integration`으로 분리)
- 기존 `tests/unit/mcp_servers/test_yf_fundamentals_mcp.py` 패턴 답습

### 선행 조건

없음. 이 Phase는 독립적으로 시작 가능.

### 리스크 플래그

- **업스트림 호환성**: `agent_config.yaml` 수정은 upstream merge 시 충돌 가능 → YAML 끝부분에 추가하여 충돌 최소화
- **pykrx 안정성**: pykrx는 KRX 웹 스크래핑 기반이라 KRX 사이트 변경 시 깨질 수 있음 → 에러 핸들링 견고하게

---

## Phase 2: pykrx 기반 Native Data Source

**목표**: `src/data_client/` fallback chain에 한국 시장 소스를 추가하여, 웹 UI의 차트/시세 기능에서도 한국 종목을 지원한다.

### 수정/추가 파일

| 작업 | 파일 | 종류 |
|------|------|------|
| DataSource 구현 | `src/data_client/korean/__init__.py` | **신규** |
| DataSource 구현 | `src/data_client/korean/data_source.py` | **신규** |
| 프로바이더 등록 | `src/data_client/registry.py` | **수정** — `_SOURCE_REGISTRY`에 `"korean"` 추가 |
| 프로바이더 체인 | `config.yaml` | **수정** — `market_data.providers`에 `{name: korean, markets: [kr]}` 추가 |
| 단위 테스트 | `tests/unit/data_client/korean/test_data_source.py` | **신규** |

### registry.py 수정 (최소)

```python
# FORK: 한국 시장 데이터 소스
def _korean_available() -> bool:
    try:
        import pykrx  # noqa: F401
        return True
    except ImportError:
        return False

async def _build_korean_source() -> MarketDataSource:
    from .korean.data_source import KoreanDataSource
    return KoreanDataSource()

_SOURCE_REGISTRY["korean"] = (_korean_available, _build_korean_source)
```

### 선행 조건

Phase 1 (pykrx 의존성이 이미 추가되어 있어야 함)

### 리스크 플래그

- **registry.py 수정**: 업스트림 파일 수정이므로 `# FORK:` 주석 필수. 향후 merge 시 충돌 가능하나 파일 끝에 추가하므로 저위험
- **티커 체계 차이**: 한국 종목은 6자리 숫자 (005930), 미국은 알파벳 (AAPL). `MarketDataProvider`의 라우팅이 market 파라미터에 의존하므로, 호출부에서 `market="kr"` 전달이 필요할 수 있음 → 호출 경로 추가 조사 필요

---

## Phase 3: DART 공시 데이터 (OpenDartReader)

**목표**: DART 전자공시 데이터를 MCP 서버로 노출한다.

### 수정/추가 파일

| 작업 | 파일 | 종류 |
|------|------|------|
| DART MCP 서버 | `mcp_servers/korean/kr_dart_mcp_server.py` | **신규** |
| 의존성 추가 | `pyproject.toml` | **수정** — `opendartreader>=0.2.2` 추가 |
| MCP 서버 등록 | `agent_config.yaml` | **수정** — `mcp.servers`에 `kr_dart` 추가 |
| DART API 키 | `.env.example` | **수정** — `DART_API_KEY` 추가 |
| 단위 테스트 | `tests/unit/mcp_servers/korean/test_kr_dart_mcp.py` | **신규** |

### 도구 설계

```python
mcp = FastMCP("KoreanDartMCP")

@mcp.tool()
def get_dart_financials(corp_code: str, year: int,
                        report_type: str = "annual") -> dict:
    """K-IFRS 기반 재무제표 (손익계산서, 재무상태표, 현금흐름표)"""

@mcp.tool()
def get_dart_disclosures(corp_code: str, start_date: str,
                         end_date: str, disclosure_type: str = "all") -> dict:
    """DART 공시 목록 조회 (주요사항, 정기보고서 등)"""

@mcp.tool()
def search_dart_corp(name: str) -> dict:
    """기업명으로 DART 고유번호(corp_code) 검색"""

@mcp.tool()
def get_dart_major_shareholders(corp_code: str) -> dict:
    """대량보유 상황보고서 (5% 룰)"""
```

### 선행 조건

Phase 1 (MCP 서버 패턴 검증 완료 후)

### 리스크 플래그

- **DART API 키 필요**: 무료 발급 가능하나 일일 호출 한도 있음 (10,000건/일)
- **corp_code 매핑**: pykrx 티커(6자리)와 DART corp_code 매핑이 필요 → OpenDartReader의 `corp_codes` DataFrame 활용

---

## Phase 4: 한국 시장 스킬 추가

**목표**: 한국 특화 분석 워크플로우를 스킬로 제공한다.

### 추가 파일

| 스킬 | 디렉토리 | 설명 |
|------|---------|------|
| DART 공시 분석 | `skills/korean/dart-analysis/SKILL.md` | 공시 요약, 주요 변동 사항 추출 |
| K-IFRS DCF | `skills/korean/kr-dcf-model/SKILL.md` | 한국 기업 맞춤 DCF (WACC: 한은 기준금리, 한국 시장 리스크 프리미엄) |
| KR 스크리너 | `skills/korean/kr-screener/SKILL.md` | KOSPI/KOSDAQ 종목 스크리닝 |
| KR 실적 분석 | `skills/korean/kr-earnings-analysis/SKILL.md` | K-IFRS 기반 실적 분석 + 컨센서스 비교 |

### SKILL.md 포맷 (예시)

```yaml
---
name: dart-analysis
description: "DART 전자공시 분석: 주요사항보고서, 사업보고서, 대량보유 변동 추출 및 투자 시사점 분석"
license: "Apache-2.0"
---

# DART 공시 분석

## 트리거
사용자가 한국 기업의 공시, 사업보고서, 주요사항보고서 분석을 요청할 때

## 워크플로우
1. `search_dart_corp(name)` 으로 corp_code 확인
2. `get_dart_disclosures(corp_code, ...)` 로 최근 공시 목록 조회
3. 주요 공시 내용 분석
4. 투자 시사점 요약
...
```

### 레지스트리 등록 (선택적)

하드코딩 레지스트리(`registry.py`)에 추가하면 스킬 목록에 즉시 표시된다. 그러나 이는 업스트림 파일 수정이므로, 초기에는 **파일시스템 디스커버리에만 의존**하여 업스트림 호환성을 유지하는 것을 권장한다.

### 선행 조건

Phase 1 + Phase 3 (MCP 도구가 존재해야 스킬에서 참조 가능)

### 리스크 플래그

- **레지스트리 미등록 시 Flash 모드 제한**: 파일시스템 디스커버리는 PTC 모드에서만 동작. Flash 모드에서도 쓰려면 레지스트리 등록 필요
- **기존 DCF 스킬과의 충돌**: `dcf-model` 스킬이 이미 존재하므로, 한국 DCF는 별도 스킬(`kr-dcf-model`)로 분리

---

## Phase 5: ECOS 매크로 데이터 (한국은행)

**목표**: 한국은행 ECOS API를 MCP 서버로 노출하여 한국 매크로 경제 데이터를 제공한다.

### 수정/추가 파일

| 작업 | 파일 | 종류 |
|------|------|------|
| ECOS MCP 서버 | `mcp_servers/korean/kr_ecos_mcp_server.py` | **신규** |
| 의존성 추가 | `pyproject.toml` | **수정** — ECOS API 클라이언트 또는 직접 HTTP |
| MCP 서버 등록 | `agent_config.yaml` | **수정** — `mcp.servers`에 `kr_ecos` 추가 |
| ECOS API 키 | `.env.example` | **수정** — `ECOS_API_KEY` 추가 |
| 단위 테스트 | `tests/unit/mcp_servers/korean/test_kr_ecos_mcp.py` | **신규** |

### 도구 설계

```python
mcp = FastMCP("KoreanEcosMCP")

@mcp.tool()
def get_kr_interest_rate(from_date: str, to_date: str) -> dict:
    """한은 기준금리 추이"""

@mcp.tool()
def get_kr_economic_indicator(indicator: str, from_date: str,
                               to_date: str) -> dict:
    """GDP, CPI, 실업률 등 주요 경제지표"""

@mcp.tool()
def get_kr_exchange_rate(currency: str, from_date: str,
                          to_date: str) -> dict:
    """원화 환율 (USD/KRW, JPY/KRW 등)"""
```

### 선행 조건

Phase 1 (MCP 서버 패턴 검증)

### 리스크 플래그

- **ECOS API 키 필요**: 한국은행에서 무료 발급, 일일 한도 비교적 넉넉
- **ECOS Python 패키지**: 공식 패키지가 없으므로 직접 HTTP 호출 또는 비공식 래퍼 사용. 의존성 최소화를 위해 `httpx`로 직접 호출 권장 (이미 프로젝트 의존성에 포함)

---

## Phase 6: 단일 사용자 최적화

**목표**: 멀티테넌시 오버헤드를 줄이고 로컬 Docker 셀프호스팅에 최적화한다.

### 수정/추가 파일

| 작업 | 파일 | 종류 |
|------|------|------|
| Docker Compose 한국 설정 | `docker-compose.override.yml` | **신규** — 한국 MCP 서버 환경변수 |
| 환경변수 프리셋 | `.env.korean` | **신규** — 한국 시장 전용 환경변수 템플릿 |
| 샌드박스에 pykrx 추가 | `Dockerfile.sandbox` | **수정** — `pip install pykrx opendartreader` 추가 |

### 구현 방향

- `.env`에 `ANTHROPIC_API_KEY` 직접 설정 → OAuth 불필요
- `HOST_MODE=oss` → Supabase 인증 우회, `AUTH_USER_ID` 고정
- Docker sandbox provider 사용 (Daytona 불필요)
- `agent_config.yaml`의 LLM을 Claude로 직접 지정

### 선행 조건

Phase 1-5 중 하나 이상 완료

### 리스크 플래그

- **Dockerfile.sandbox 수정**: 업스트림 파일이지만 샌드박스 내 패키지 설치이므로 `# FORK:` 주석으로 표시
- **보안**: 단일 사용자이므로 인증 단순화 가능하나, 외부 노출 시 문제 → Docker 네트워크 격리 유지

---

## 의존성 추가 위치 정리

`pyproject.toml`의 `[project.dependencies]` 섹션:

```toml
# FORK: 한국 시장 데이터
"pykrx>=1.0.45",
"opendartreader>=0.2.2",
```

ECOS는 별도 패키지 없이 `httpx` (이미 포함)로 직접 호출.

---

## Phase별 작업 순서 다이어그램

```
Phase 1 (pykrx MCP)          ← 단독 시작 가능
    │
    ├── Phase 2 (Native DataSource)
    │
    ├── Phase 3 (DART MCP)
    │       │
    │       └── Phase 4 (한국 스킬)
    │
    └── Phase 5 (ECOS MCP)

Phase 6 (단일 사용자 최적화)  ← Phase 1+ 이후 언제든
```

---

## 전체 리스크 플래그 요약

| 리스크 | 영향도 | 대응 |
|--------|-------|------|
| `agent_config.yaml` 머지 충돌 | 중간 | YAML 끝부분에 추가, 명확한 `# FORK:` 주석 |
| `registry.py` 머지 충돌 | 낮음 | 파일 끝에 추가, 3줄 이하 변경 |
| pykrx KRX 사이트 변경 | 중간 | 에러 핸들링 + 버전 고정 |
| 한국 티커(숫자) vs 미국 티커(알파벳) 혼동 | 낮음 | 도구 설명에 명시, 티커 유효성 검증 추가 |
| DART/ECOS API 키 관리 | 낮음 | `.env`에 저장, vault 사용은 Phase 6에서 결정 |
| `Dockerfile.sandbox` 수정 | 낮음 | 패키지 설치만 추가, `# FORK:` 주석 |
| `registry.py`의 `SKILL_REGISTRY` 수정 | 중간 | Phase 4에서는 파일시스템 디스커버리만 사용하여 회피 |
