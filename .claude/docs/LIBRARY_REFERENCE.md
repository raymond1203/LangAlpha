# LIBRARY_REFERENCE.md — 프로젝트 핵심 라이브러리 최신 레퍼런스

> Context7 MCP로 2026-04-23 기준 최신 문서를 수집한 결과.
> Phase 1-5 구현 시 참조용.

---

## 1. pykrx (한국 주식 시장 데이터)

> Source: `/sharebook-kr/pykrx` — Code Snippets: 189, Reputation: High, Score: 85.65

### 설치

```bash
pip install pykrx
```

### 핵심 API

```python
from pykrx import stock
```

#### 종목 조회

```python
# 전체 티커 목록 (KOSPI, KOSDAQ, KONEX, ALL)
tickers = stock.get_market_ticker_list("20230101", market="KOSPI")
# ['095570', '006840', '027410', ...]

# 티커 → 종목명
name = stock.get_market_ticker_name("005930")
# '삼성전자'
```

#### OHLCV (시가/고가/저가/종가/거래량)

```python
# 특정 종목 기간별 OHLCV
df = stock.get_market_ohlcv("20220720", "20220810", "005930")
# columns: 시가, 고가, 저가, 종가, 거래량, 거래대금, 등락률

# 특정 일자 전종목 OHLCV
df = stock.get_market_ohlcv("20210122", market="KOSPI")
# index: 티커, columns: 시가, 고가, 저가, 종가, 거래량, 거래대금, 등락률

# 수정주가 (기본값 adjusted=True)
df = stock.get_market_ohlcv("20220720", "20220810", "005930", adjusted=True)
```

#### 시가총액

```python
# 특정 종목 기간별 시가총액
df = stock.get_market_cap("20230101", "20230131", "005930")
# columns: 시가총액, 거래량, 거래대금, 상장주식수

# 특정 일자 전종목 시가총액 (시가총액순 정렬)
df = stock.get_market_cap("20230102")
# index: 티커, columns: 종가, 시가총액, 거래량, 거래대금, 상장주식수

# 월별/연별 리샘플링
df = stock.get_market_cap("20230101", "20231231", "005930", freq="m")
```

#### 펀더멘탈 (PER, PBR, DIV, EPS, BPS)

```python
# 특정 종목 기간별 펀더멘탈
df = stock.get_market_fundamental("20210104", "20210108", "005930")
# columns: BPS, PER, PBR, EPS, DIV, DPS

# 특정 일자 전종목 펀더멘탈
df = stock.get_market_fundamental("20210104", market="KOSDAQ")

# 월별 리샘플링
df = stock.get_market_fundamental("20200101", "20200430", "005930", freq="m")
```

#### ETF

```python
# ETF 티커 목록
etf_tickers = stock.get_etf_ticker_list("20230102")

# ETF OHLCV + NAV
df = stock.get_etf_ohlcv_by_date("20230101", "20230131", "152100")
# columns: NAV, 시가, 고가, 저가, 종가, 거래량, 거래대금, 기초지수

# 특정 일자 전체 ETF OHLCV
df = stock.get_etf_ohlcv_by_ticker("20230102")
```

#### 투자자별 거래실적

```python
# KOSPI/KOSDAQ/KONEX/ALL 지정 가능
# 세 번째 파라미터로 시장 지정
```

### 주의사항

- 날짜 포맷: `"YYYYMMDD"` (문자열)
- 결과: `pandas.DataFrame`
- 조회 기간이 길수록 시간 소요 (KRX 웹 스크래핑 기반)
- 외국인보유주식수: D-2까지만 유효 (D-1은 0)

---

## 2. OpenDartReader (DART 전자공시)

> Source: `/financedata/opendartreader` — Code Snippets: 96, Reputation: High

### 설치 & 초기화

```bash
pip install opendartreader
```

```python
import OpenDartReader

dart = OpenDartReader("YOUR_DART_API_KEY")
```

### 핵심 API

#### 공시 목록 조회

```python
# 특정 기업의 정기보고서 ('A'=정기, 'B'=주요사항, 'C'=발행공시, 'D'=지분공시, 'E'=기타)
dart.list(code='005930', kind='A', start='2019-01-01', end='2019-12-31')

# 전체 공시 목록 (1999년~현재)
dart.list('005930')

# kind_detail: 상세 공시 유형 코드
# final: True(최종본만) / False(중간본 포함)
```

#### 기업 정보

```python
# 기업 개황 (종목코드, 고유번호, 기업명 모두 가능)
dart.company('005930')         # dict 반환

# 기업명으로 검색
dart.company_by_name('삼성전자')  # list[dict] 반환

# 고유번호(corp_code) 조회
corp_code = dart.find_corp_code('005930')

# 전체 기업코드 DataFrame
dart.corp_codes  # DataFrame (corp_code, corp_name, stock_code 등)
```

#### 재무제표

```python
# 주요 재무제표 (재무상태표, 손익계산서)
dart.finstate('삼성전자', 2021)

# 분기 보고서 (reprt_code: '11013'=1Q, '11012'=반기, '11014'=3Q, '11011'=사업보고서)
dart.finstate('삼성전자', 2021, reprt_code='11013')

# 여러 기업 비교 (종목코드, 고유번호, 기업명 모두 가능)
dart.finstate('005930, 000660, 005380', 2021)
dart.finstate('삼성전자, SK하이닉스, 현대자동차', 2021)

# 전체 재무제표 (XBRL 기반 전 항목)
dart.finstate_all('005930', 2021)

# 재무제표 XBRL 원본 파일 다운로드
dart.finstate_xml('20220308000798', save_as='삼성전자_2021_XBRL.zip')
```

#### 사업보고서 주요 정보

```python
# key_word: '증자', '배당', '자기주식', '최대주주', '임원', '직원' 등
dart.report('005930', '배당', 2021, reprt_code='11011')
```

#### 지분공시

```python
# 대량보유 상황보고 (5% 룰)
dart.major_shareholders('삼성전자')

# 임원·주요주주 소유보고
dart.major_shareholders_exec('005930')
```

#### 원문 문서

```python
# 공시 원문 (XML 텍스트)
xml_text = dart.document('20190401004781')  # rcp_no 8자리
```

### 주의사항

- **DART API 키 필요**: [OpenDART](https://opendart.fss.or.kr/) 에서 무료 발급
- 일일 호출 한도: 10,000건/일
- 입력 파라미터: 종목코드(`005930`), 고유번호(`00126380`), 기업명(`삼성전자`) 모두 허용
- reprt_code: `11011`=사업보고서, `11013`=1분기, `11012`=반기, `11014`=3분기

---

## 3. MCP Python SDK + FastMCP

> Source: `/modelcontextprotocol/python-sdk` — Score: 81.06

### 이 프로젝트에서 사용하는 패턴

프로젝트는 `mcp.server.fastmcp.FastMCP`를 사용한다 (MCP SDK에 포함).

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ServerName")

@mcp.tool()
def my_tool(param: str) -> dict:
    """도구 설명 (자동으로 description이 됨)"""
    return {"result": "..."}

if __name__ == "__main__":
    mcp.run(transport="stdio")  # 이 프로젝트는 stdio 사용
```

### 주요 패턴 (이 프로젝트 기준)

**동기 서버** (yfinance 계열):
```python
mcp = FastMCP("YFinancePriceMCP")

@mcp.tool()
def get_stock_history(ticker: str, period: str = "1mo") -> dict:
    """..."""
    ...

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**비동기 서버 + Lifespan** (FMP 계열):
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    # 초기화
    try:
        yield
    finally:
        # 정리
        await cleanup()

mcp = FastMCP("FundamentalsMCP", lifespan=_lifespan)

@mcp.tool()
async def get_data(symbol: str) -> dict:
    ...
```

### Transport 옵션

| Transport | 용도 | 이 프로젝트 |
|-----------|------|------------|
| `stdio` | subprocess 통신 | **기본 사용** |
| `sse` | HTTP SSE 스트리밍 | 일부 서버 |
| `streamable-http` | 프로덕션 HTTP | 미사용 |

### 에러 처리 패턴 (이 프로젝트 관례)

```python
@mcp.tool()
def my_tool(param: str) -> dict:
    try:
        # ... 작업
        return {"data_type": "...", "source": "provider", "data": [...], "count": N}
    except Exception as e:
        return {"error": str(e)}
```

- 예외를 raise하지 않고 `{"error": "..."}` dict로 반환
- 응답 봉투: `{data_type, source, data, count}` 통일

---

## 4. LangGraph (에이전트 프레임워크)

> Source: `/websites/langchain_oss_python_langgraph` — Score: 88.55

### 이 프로젝트에서의 사용

프로젝트는 `create_agent()`를 사용 (hand-written StateGraph 아님):

```python
from deepagents import create_agent  # 내부 라이브러리

agent = create_agent(
    model,
    system_prompt=system_prompt,
    tools=tools,
    middleware=deepagent_middleware,    # 23계층
    checkpointer=checkpointer,        # PostgreSQL
    store=store,
)
```

### 미들웨어 패턴

```python
agent = create_agent(
    model="...",
    tools=[...],
    middleware=[
        ToolCallLimitMiddleware(tool_name="...", run_limit=1),
        # ... 추가 미들웨어
    ],
    checkpointer=MemorySaver(),
)
```

### Checkpointer

이 프로젝트: `AsyncPostgresSaver` (LangGraph 내장)
- 별도 PostgreSQL 풀에 체크포인트 저장
- `MEMORY_DB_NAME` 환경변수로 DB 지정

---

## 5. LangChain (도구 프레임워크)

> Source: `/websites/langchain_oss_python_langchain` — Score: 70.24

### 커스텀 도구 생성 (이 프로젝트 패턴)

```python
from langchain.tools import tool

@tool("get_stock_daily_prices")
def get_stock_daily_prices(symbol: str, period: str = "1mo") -> str:
    """주식 일별 OHLCV 가격 데이터 조회.

    Args:
        symbol: 종목 티커 (예: AAPL, 005930)
        period: 조회 기간 (1d, 5d, 1mo, 3mo, 6mo, 1y)
    """
    # ... 구현
    return result
```

### Pydantic 스키마로 입력 검증

```python
from pydantic import BaseModel, Field

class StockInput(BaseModel):
    symbol: str = Field(description="종목 티커")
    period: str = Field(default="1mo", description="조회 기간")

@tool(args_schema=StockInput)
def get_stock_data(symbol: str, period: str = "1mo") -> str:
    """..."""
    ...
```

### 이 프로젝트의 도구 팩토리 패턴

```python
def create_execute_code_tool(backend, mcp_registry, thread_id=""):
    @tool("ExecuteCode")
    async def execute_code(code: str, description: str | None = None) -> str:
        """..."""
        ...
    return execute_code
```

---

## 6. ECOS (한국은행 경제통계)

> Context7에 등록되지 않음. 직접 HTTP 호출 예정.

### API 개요

- 기본 URL: `https://ecos.bok.or.kr/api/`
- 인증: API 키 (한국은행에서 무료 발급)
- 응답: XML 또는 JSON
- 주요 엔드포인트:
  - `StatisticSearch`: 통계 항목 검색
  - `StatisticTableList`: 통계표 목록
  - `StatisticItemList`: 통계 항목 목록

### 호출 패턴 (httpx 사용 예정)

```python
import httpx

ECOS_BASE = "https://ecos.bok.or.kr/api"

async def get_kr_interest_rate(api_key: str, from_date: str, to_date: str):
    url = f"{ECOS_BASE}/StatisticSearch/{api_key}/json/kr/1/100/722Y001/MM/{from_date}/{to_date}/0101000"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return resp.json()
```

### 주요 통계코드

| 코드 | 항목 |
|------|------|
| `722Y001` | 한국은행 기준금리 |
| `901Y009` | GDP (국내총생산) |
| `901Y010` | GDP 성장률 |
| `021Y125` | 소비자물가지수 (CPI) |
| `731Y001` | 원/달러 환율 |
