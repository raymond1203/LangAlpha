# CODEBASE_MAP.md — LangAlpha 코드베이스 지도

> 이 문서는 `ginlix-ai/LangAlpha` 포크의 코드베이스를 한국 시장 커스터마이징 관점에서 분석한 것이다.
> 모든 판단에는 근거 파일·라인 번호를 명시한다.

---

## 1. 전체 디렉토리 구조

```
Alpha/
├── server.py                      # uvicorn 진입점 (port 8000)
├── config.yaml                    # 인프라 설정 (Redis, CORS, 시장 데이터 프로바이더 체인)
├── agent_config.yaml              # 에이전트 설정 (LLM, MCP, 샌드박스, 서브에이전트)
├── .env.example                   # 환경변수 템플릿 (API 키, DB 연결)
├── pyproject.toml                 # Python 의존성 (FastAPI, LangGraph, MCP 등)
├── Makefile                       # 개발 명령어 (up, dev, test, migrate)
├── docker-compose.yml             # 풀스택 (postgres, redis, backend, frontend)
├── Dockerfile.sandbox             # 샌드박스 실행 환경 (Ubuntu 24.04)
├── alembic.ini                    # DB 마이그레이션 설정
│
├── src/
│   ├── server/                    # FastAPI 앱, 라우터, 핸들러, 서비스
│   │   ├── app/setup.py           # 앱 라이프사이클, 미들웨어, 라우터 등록
│   │   ├── handlers/chat/         # PTC/Flash 워크플로우, LLM 설정 리졸브
│   │   ├── database/              # PostgreSQL 풀, CRUD (raw psycopg3, ORM 없음)
│   │   ├── services/              # 세션, 워크스페이스, 캐시, 자동화
│   │   └── auth/                  # 인증 (Supabase 또는 로컬 dev)
│   │
│   ├── ptc_agent/                 # 핵심 에이전트 라이브러리
│   │   ├── agent/agent.py         # PTCAgent 팩토리, 미들웨어 스택 조립
│   │   ├── agent/middleware/      # 23계층 미들웨어 (아래 상세)
│   │   ├── agent/tools/           # 네이티브 도구 (ExecuteCode, Bash, 파일시스템)
│   │   ├── agent/subagents/       # 서브에이전트 레지스트리 + 컴파일러
│   │   ├── agent/flash/           # Flash 모드 (샌드박스 없는 경량 에이전트)
│   │   ├── agent/prompts/         # Jinja2 시스템 프롬프트 템플릿
│   │   ├── core/mcp_registry.py   # MCP 서버 연결·관리
│   │   ├── core/tool_generator.py # MCP 도구 → Python 래퍼 코드 생성
│   │   ├── core/session.py        # 세션 라이프사이클
│   │   └── config/                # AgentConfig, CoreConfig 모델
│   │
│   ├── tools/                     # LangChain BaseTool 구현
│   │   ├── market_data/           # 주식 가격, 옵션, 섹터, 스크리너
│   │   ├── sec/                   # SEC 10-K/10-Q/8-K 파싱
│   │   ├── search_services/       # 웹 검색 (Tavily, Serper, Bocha)
│   │   ├── crawler/               # 웹 페이지 크롤링 + 추출
│   │   ├── user_profile/          # 워치리스트, 포트폴리오 관리
│   │   ├── automation/            # 크론/가격 트리거
│   │   └── onboarding/            # 온보딩 플로우
│   │
│   ├── llms/                      # LLM 프로바이더 래퍼
│   │   ├── llm.py                 # ModelConfig: models.json + providers.json 로드
│   │   ├── extension/anthropic_oauth.py  # Claude OAuth Bearer 인증
│   │   └── manifest/              # models.json, providers.json
│   │
│   ├── data_client/               # 시장 데이터 프로바이더 추상화
│   │   ├── base.py                # Protocol 정의 (MarketDataSource 등)
│   │   ├── registry.py            # 프로바이더 팩토리 + fallback chain
│   │   ├── market_data_provider.py # 시장별 라우팅 + fallback
│   │   ├── fmp/                   # FMP 구현
│   │   ├── ginlix_data/           # ginlix-data 구현
│   │   └── yfinance/              # yfinance 구현 (무료 fallback)
│   │
│   ├── config/                    # 인프라 설정 (settings.py, env.py, models.py)
│   └── utils/                     # Redis 캐시, 스토리지, 트래킹
│
├── mcp_servers/                   # FastMCP 기반 데이터 도구 서버 (10개)
├── skills/                        # 에이전트 스킬 (28개, SKILL.md 기반)
├── migrations/versions/           # Alembic 마이그레이션 (9개)
├── tests/                         # unit (163) + integration (62)
├── libs/ptc-cli/                  # CLI 클라이언트 (SSE 스트리밍)
├── web/                           # React 19 프론트엔드
├── scripts/                       # 설정 위저드, DB 시작, 유틸리티
└── deploy/                        # Docker 빌드 (dev/prod)
```

---

## 2. MCP 서버 등록·노출 흐름

### 2.1 MCP 서버 정의 (10개)

| 서버 | 파일 | 도구 수 | 프로바이더 | Async | Fallback |
|------|------|---------|-----------|-------|----------|
| price_data | `mcp_servers/price_data_mcp_server.py` | 3 | ginlix → FMP | Yes | **Yes** |
| fundamentals | `mcp_servers/fundamentals_mcp_server.py` | 9 | FMP | Yes | No |
| macro | `mcp_servers/macro_mcp_server.py` | 5 | FMP | Yes | No |
| options | `mcp_servers/options_mcp_server.py` | 3 | ginlix | Yes | No |
| yf_price | `mcp_servers/yf_price_mcp_server.py` | 4 | yfinance | No | No |
| yf_fundamentals | `mcp_servers/yf_fundamentals_mcp_server.py` | 9 | yfinance | No | No |
| yf_analysis | `mcp_servers/yf_analysis_mcp_server.py` | 10 | yfinance | No | No |
| yf_market | `mcp_servers/yf_market_mcp_server.py` | 7 | yfinance | No | No |
| x_api | `mcp_servers/x_mcp_server.py` | 5 | X API v2 | Yes | No |
| **합계** | | **55** | | | |

### 2.2 등록 흐름

```
agent_config.yaml (mcp.servers 섹션)
  ↓ 파싱
AgentConfig.mcp.servers: list[MCPServerConfig]
  ↓ 세션 초기화 시
MCPRegistry.connect_all()                           # core/mcp_registry.py:653
  ↓ 서버별 병렬 연결
MCPServerConnector.__aenter__()                     # core/mcp_registry.py:229
  ↓ transport별 분기 (stdio/SSE/HTTP)
  ↓ StdioServerParameters → subprocess 시작         # core/mcp_registry.py:330-362
  ↓ session.list_tools() → MCPToolInfo 수집         # core/mcp_registry.py:388
```

### 2.3 도구 노출 경로 (PTC 모드)

MCP 도구는 LLM에 **직접 노출되지 않는다**. 대신:

1. **시스템 프롬프트에 요약 주입**: `build_tool_summary_from_registry()` (`prompts/formatter.py:305-340`)가 서버별 도구 목록을 `from tools.{server} import {func}` 형태로 포맷
2. **Python 래퍼 코드 생성**: `ToolFunctionGenerator` (`core/tool_generator.py:15`)가 MCP 도구를 Python 함수로 변환
3. **래퍼 코드를 샌드박스에 업로드**: 각 서버별 `tools/{server_name}.py` 모듈 + `tools/mcp_client.py` (JSON-RPC 클라이언트)
4. **LLM이 `ExecuteCode` 도구로 코드 실행**: `from tools.fundamentals import get_financial_statements` → `_call_mcp_tool()` → stdio JSON-RPC → MCP 서버

이 패턴이 **Programmatic Tool Calling (PTC)** 의 핵심이다.

### 2.4 agent_config.yaml의 MCP 서버 설정 구조

```yaml
mcp:
  tool_exposure_mode: "summary"    # 시스템 프롬프트에서 도구 노출 수준
  servers:
    - name: "price_data"
      enabled: true
      command: "uv"
      args: ["run", "python", "mcp_servers/price_data_mcp_server.py"]
      env:
        FMP_API_KEY: "${FMP_API_KEY}"
      tool_exposure_mode: "detailed"
```

> **한국 시장 확장 포인트**: `mcp_servers/korean/` 디렉토리에 새 MCP 서버를 만들고, `agent_config.yaml`의 `mcp.servers` 배열에 항목을 추가하면 된다. 기존 파일 수정 불필요.

---

## 3. 스킬 로딩 메커니즘

### 3.1 스킬 구조

```
skills/{skill-name}/
├── SKILL.md              # YAML 프론트매터 + 마크다운 문서
└── references/           # (선택) 참고 문서
```

**SKILL.md 프론트매터 스펙** (`middleware/skills/discovery.py:28-54`):

```yaml
---
name: dcf-model                    # 필수. 디렉토리명과 일치해야 함 (1-64자)
description: "DCF 밸류에이션..."    # 필수 (1-1024자)
license: "Apache-2.0"             # 선택
compatibility: "..."              # 선택 (500자 이하)
allowed-tools: [...]              # 선택
metadata: {}                      # 선택
---
```

### 3.2 이중 레지스트리 시스템

1. **하드코딩 레지스트리** (`middleware/skills/registry.py:78-287`):
   - 28개 `SkillDefinition` 객체가 `SKILL_REGISTRY` dict에 정의
   - 각 정의에 `exposure` 필드: `"ptc"` | `"flash"` | `"both"` | `"hidden"`
   - 대부분의 스킬은 `tools=[]` (도구 없음 — 문서 기반)
   - 도구가 있는 스킬: `user-profile`, `onboarding`, `automation` (3개)

2. **파일시스템 디스커버리** (`middleware/skills/discovery.py:228-362`):
   - PTC 모드에서 `abefore_agent()` 시 샌드박스 파일시스템 스캔
   - `skills-lock.json` 캐시로 불필요한 SKILL.md 다운로드 방지
   - 알 수 없는 스킬은 `confirmed=False`로 플래그

### 3.3 로딩 경로

**PTC 모드** (`middleware/skills/middleware.py:263-286`):
- `LoadSkill` 도구 **없음**
- 에이전트가 `Read("skills/{name}/SKILL.md")` 호출 시 자동 감지
- `_skill_md_to_name` 매핑으로 SKILL.md 경로 → 스킬명 매칭
- 매칭되면 해당 스킬의 도구가 자동 활성화

**Flash 모드** (`middleware/skills/middleware.py:159-184`):
- `LoadSkill(skill_name="...")` 도구가 명시적으로 노출
- 호출 시 SKILL.md 콘텐츠 + 도구 목록을 인라인 반환

**도구 필터링** (`middleware/skills/middleware.py:468-541`):
- `awrap_model_call()` 에서 매 LLM 호출 전 도구 필터링
- 로드된 스킬의 도구만 모델에 노출
- 비스킬 도구는 항상 포함

> **한국 시장 확장 포인트**: `skills/korean/{skill-name}/SKILL.md` 파일을 만들면 파일시스템 디스커버리가 자동 감지한다. 하드코딩 레지스트리에 등록하려면 `registry.py`의 `SKILL_REGISTRY`에 추가해야 하지만, 이는 업스트림 호환성 위험이 있으므로 별도 파일에서 확장하는 방법을 고안해야 한다.

---

## 4. 에이전트 설정 플로우

### 4.1 설정 파일 계층

```
.env                    → 크리덴셜, DB URL, HOST_MODE
config.yaml             → 인프라 (Redis, CORS, workflow 타임아웃, 시장 데이터 프로바이더 체인)
agent_config.yaml       → 에이전트 능력 (LLM, MCP, 샌드박스, 서브에이전트, 컴팩션)
```

### 4.2 설정 로딩 체인

```
server.py → src/server/app/setup.py:193-214 (lifespan 중)
  ↓
load_from_files()                             # ptc_agent/config/loaders.py:106-151
  ↓ 검색 순서:
  1. 환경변수 PTC_CONFIG_FILE
  2. 현재 작업 디렉토리 (agent_config.yaml)
  3. Git 루트
  4. ~/.ptc-agent/
  ↓
AgentConfig 생성                              # ptc_agent/config/agent.py
  ├── SandboxConfig (provider: daytona|docker)
  ├── MCPConfig (servers: list[MCPServerConfig])
  ├── SkillsConfig (enabled, sandbox_skills_base)
  ├── SubagentsConfig (enabled, definitions)
  ├── CompactionConfig (threshold, keep_messages)
  └── LLM 설정 (name, flash, compaction, fallback)
```

### 4.3 인프라 설정 (config.yaml)

| 설정 | 경로 | 값 |
|------|------|-----|
| 디버그 모드 | `debug` | `false` |
| PTC 재귀 한도 | `recursion_limits.ptc` | 2000 |
| 워크플로우 타임아웃 | `workflow_timeout` | 3200초 |
| SSE 킵얼라이브 | `sse_keepalive` | 15초 |
| Redis 캐시 TTL (결과) | `cache.result_ttl` | 300초 |
| 시장 데이터 프로바이더 체인 | `market_data.providers` | ginlix-data(US) → FMP(all) → yfinance(all) |

---

## 5. 데이터 프로바이더 Fallback Chain

### 5.1 아키텍처 개요

두 개의 독립적인 데이터 레이어가 존재한다:

#### A. Native Tool 레이어 (src/tools/market_data/ + src/data_client/)

`config.yaml`의 `market_data.providers` 순서에 따라 라우팅:

```
config.yaml:142-149
  providers:
    - name: ginlix-data, markets: [us]    ← 미국 전용
    - name: fmp, markets: [all]           ← 글로벌 fallback
    - name: yfinance, markets: [all]      ← 무료 fallback
```

**팩토리** (`src/data_client/registry.py:118-160`):
1. 각 프로바이더의 가용성 체크 (`_ginlix_data_available()`, `_fmp_available()`, `_yfinance_available()`)
2. 가용한 프로바이더만 `ProviderEntry`로 등록
3. `MarketDataProvider`가 요청의 market 파라미터에 따라 적절한 소스로 라우팅

**Protocol 정의** (`src/data_client/base.py`):
- `MarketDataSource` (L28-84): OHLCV 가격 데이터 (`get_intraday`, `get_daily`, `get_snapshots`)
- `NewsDataSource` (L87-112): 뉴스 피드
- `FinancialDataSource` (L115-144): 재무제표, 애널리스트, 실적
- `MarketIntelSource` (L147-173): 옵션, 공매도, 유동 주식

> **한국 시장 확장 포인트**: `src/data_client/korean/` 디렉토리에 `pykrx` 기반 `MarketDataSource` 구현을 만들고, `registry.py`의 `_SOURCE_REGISTRY`에 `"korean": (_korean_available, _build_korean_source)` 를 추가하면 된다. `config.yaml`의 프로바이더 체인에 `{name: korean, markets: [kr]}`을 추가하면 한국 종목은 이 소스로 라우팅된다.

#### B. MCP 서버 레이어 (mcp_servers/)

PTC 모드에서 `ExecuteCode`를 통해 호출. 각 MCP 서버가 자체적으로 데이터 소스를 관리.

**유일한 fallback 구현**: `price_data_mcp_server.py:96-178`

```python
# 1초 인터벌: ginlix-data 전용
if interval == "1s":
    return await _ginlix.fetch_stock_data(...)

# 기타 인터벌: ginlix → FMP fallback
ginlix_result = await _ginlix.fetch_stock_data(...)
ginlix_resp = _ginlix_result_to_response(ginlix_result, ...)
if ginlix_resp is not None:         # 성공 → 반환
    return ginlix_resp
                                     # None → FMP fallback
fmp_client = await get_fmp_client()
# ... FMP 호출
```

나머지 MCP 서버는 단일 프로바이더 직접 호출 (fallback 없음).

---

## 6. 미들웨어 스택 (23계층)

`src/ptc_agent/agent/agent.py:603-628`에서 조립된다. 바깥쪽(먼저 실행) → 안쪽(나중 실행) 순서:

### 6.1 Main + SubAgent 공유 미들웨어

| # | 미들웨어 | 파일 | 역할 | 커스텀 관련도 |
|---|---------|------|------|-------------|
| 1 | `LargeResultEvictionMiddleware` | agent.py:606 | 큰 도구 결과를 샌드박스로 퇴출 | 낮음 |
| 2 | `SubAgentMiddleware` | agent.py:609-616 | 서브에이전트 디스패치 | 낮음 |
| 3 | `ToolArgumentParsingMiddleware` | agent.py:359 | 도구 인자 검증/파싱 | 낮음 |
| 4 | `ProtectedPathMiddleware` | agent.py:360-362 | denied_directories 접근 차단 | 낮음 |
| 5 | `CodeValidationMiddleware` | agent.py:363 | Python 코드 보안 검증 | 낮음 |
| 6 | `ToolErrorHandlingMiddleware` | agent.py:364 | 도구 에러 포맷팅 | 낮음 |
| 7 | `LeakDetectionMiddleware` | agent.py:365-368 | vault 시크릿 유출 탐지 | **읽기만** |
| 8 | `ToolResultNormalizationMiddleware` | agent.py:369 | 결과 포맷 정규화 | 낮음 |
| 9 | `FileOperationMiddleware` | agent.py:374-378 | write/edit SSE 이벤트 발생 | 낮음 |
| 10 | `TodoWriteMiddleware` | agent.py:382 | TodoWrite SSE 이벤트 | 낮음 |
| 11 | `MultimodalMiddleware` | agent.py:385-390 | 이미지/PDF 처리 | 낮음 |
| 12 | **`SkillsMiddleware`** | agent.py:409-417 | **스킬 로딩·도구 필터링** | **높음** |

### 6.2 Main 전용 미들웨어

| # | 미들웨어 | 파일 | 역할 | 커스텀 관련도 |
|---|---------|------|------|-------------|
| 13 | `SteeringMiddleware` | agent.py:425 | Redis 스티어링 메시지 체크 | 낮음 |
| 14 | `BackgroundSubagentMiddleware` | agent.py:433 | 비동기 백그라운드 태스크 | 낮음 |
| 15 | `HumanInTheLoopMiddleware` | agent.py:447 | 인터럽트/플랜 모드 | 낮음 |
| 16 | `PlanModeMiddleware` | agent.py:452 | submit_plan 도구 (조건부) | 낮음 |
| 17 | `AskUserMiddleware` | agent.py:457 | ask_user 도구 | 낮음 |

### 6.3 스택 꼬리 (캐싱·복원력)

| # | 미들웨어 | 파일 | 역할 | 커스텀 관련도 |
|---|---------|------|------|-------------|
| 18 | `CompactionMiddleware` | agent.py:558 | 컨텍스트 윈도우 관리 | 낮음 |
| 19 | Model Resilience (Fallback+Retry) | agent.py:561 | 모델 장애 대응 | 낮음 |
| 20 | `AnthropicPromptCachingMiddleware` | agent.py:621 | 프롬프트 캐싱 브레이크포인트 | 낮음 |
| 21 | `EmptyToolCallRetryMiddleware` | agent.py:622 | 빈 도구 호출 재시도 | 낮음 |
| 22 | `WorkspaceContextMiddleware` | agent.py:624 | agent.md 주입 (캐시 브레이크포인트 이후) | **중간** |
| 23 | `RuntimeContextMiddleware` | agent.py:625 | 시간 + 사용자 프로필 주입 | **중간** |

> **내가 건드릴 가능성 있는 지점**:
> - **#12 SkillsMiddleware**: 한국 시장 스킬을 로드하기 위해 디스커버리 경로가 올바르게 작동하는지 확인 필요
> - **#22 WorkspaceContextMiddleware**: agent.md에 한국 시장 컨텍스트를 추가할 수 있음
> - **#23 RuntimeContextMiddleware**: 사용자 프로필에 한국 타임존/로케일 반영

---

## 7. BYOK / 모델 Resolution 흐름

### 7.1 모델 레지스트리

**파일**: `src/llms/llm.py`

`ModelConfig` 클래스가 두 매니페스트를 로드:
- `src/llms/manifest/models.json` — 모델 파라미터 (이름, 토큰 한도 등)
- `src/llms/manifest/providers.json` — 프로바이더 설정 (SDK, 변형 모델)

프로바이더는 그룹 키 아래 `variants`를 가지며, BYOK 키 조회 시 부모-자식 관계를 따라 fan-out한다.

### 7.2 LLM 리졸브 경로

```
AgentConfig.get_llm_client()          # ptc_agent/config/agent.py:460-489
  ├── 직접 전달: config.llm_client → 즉시 반환
  └── 이름 기반: config.llm.name → src.llms.create_llm(name)
                                    → ensure_model_in_manifest()
                                    → LangChain BaseChatModel 반환
```

### 7.3 BYOK 키 리졸브 (서버 핸들러 측)

**파일**: `src/server/handlers/chat/llm_config.py`

```
_resolve_custom_model_byok(user_id, model_name)
  ↓ 조회 순서:
  1. 모델명으로 직접 매칭
  2. provider 필드로 매칭
  3. 부모 + 형제 모델로 fan-out
  ↓
  user_api_keys 테이블 (AES-GCM 암호화)
```

### 7.4 Claude OAuth 경로

**파일**: `src/llms/extension/anthropic_oauth.py`

`ChatAnthropicOAuth` 클래스:
- `api_key`를 `auth_token`으로 이동 → `Authorization: Bearer` 헤더로 전송
- Claude Code 아이덴티티를 시스템 프롬프트에 prepend (Sonnet/Opus 접근 요건)
- `api_key`를 null로 설정하여 SDK의 `ANTHROPIC_API_KEY` env 폴백 방지

> **단일 사용자 최적화 시**: BYOK 테이블 대신 `.env`에 `ANTHROPIC_API_KEY`를 직접 설정하면 가장 단순하다. OAuth 경로는 건드리지 않아도 된다.

---

## 8. 데이터베이스 스키마

`migrations/versions/001_initial_schema.py` 기준 핵심 테이블 17개:

| 테이블 | 역할 |
|--------|------|
| `users` | 사용자 프로필 (user_id PK, email, timezone, BYOK 플래그) |
| `workspaces` | 작업 환경 (1:1 Daytona 샌드박스, status enum, config JSONB) |
| `conversation_threads` | 대화 스레드 (workspace FK) |
| `conversation_queries` | 사용자 질문 (thread FK, turn_index) |
| `conversation_responses` | 에이전트 응답 (sse_events JSONB) |
| `conversation_usages` | 토큰/비용 추적 |
| `user_api_keys` | BYOK 암호화 키 (BYTEA) |
| `user_oauth_tokens` | OAuth 토큰 (BYTEA) |
| `watchlists` / `watchlist_items` | 관심 종목 |
| `user_portfolios` | 보유 종목 |
| `automations` / `automation_executions` | 스케줄 트리거 |
| `workspace_vault_secrets` | 워크스페이스별 시크릿 (migration 003) |

**LangGraph 인프라**: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `store`

> **한국 시장 확장**: 스키마 변경 불필요. `pykrx`/`OpenDartReader`는 외부 API이므로 DB 테이블 추가 없이 MCP 서버/도구로 래핑하면 된다.

---

## 9. 기타 주요 구성요소

### 9.1 서브에이전트

`agent_config.yaml:249-273`에서 활성화:
- `general-purpose`, `research`, `data-prep`, `equity-analyst`, `report-builder`

`SubagentRegistry` + `SubagentCompiler` (`agent/subagents/`)가 도구셋과 함께 컴파일.

### 9.2 프롬프트 시스템

Jinja2 템플릿: `src/ptc_agent/agent/prompts/templates/`
설정: `prompts/config/prompts.yaml`
프리뷰: `scripts/utils/render_prompt.py`

### 9.3 Docker 샌드박스

`Dockerfile.sandbox` (122줄): Ubuntu 24.04 기반. Python 3, Node 24, LibreOffice, Docker, 데이터 분석 라이브러리 프리인스톨.

### 9.4 FastAPI 라우터 (24개)

`src/server/app/setup.py:500-595`에서 등록. 주요:
- `/api/v1/threads/*` — 대화 CRUD + 메시지 스트리밍
- `/api/v1/workspaces/*` — 워크스페이스 관리
- `/api/v1/market-data/*` — 시장 데이터 프록시
- `/api/v1/users/me/api-keys` — BYOK 관리
- `/api/v1/skills` — 스킬 목록

### 9.5 Redis 캐시

`src/utils/cache/redis_cache.py`: 비동기 커넥션 풀링, JSON 직렬화, TTL, SWR 지원.
주요 캐시 키: `ohlcv:daily:{symbol}`, `workflow_events:{thread_id}`, `cancel_flag:{thread_id}`

---

## 10. 한국 시장 확장 영향 분석 요약

| 확장 영역 | 기존 파일 수정 필요 여부 | 수정 지점 |
|-----------|----------------------|----------|
| 한국 MCP 서버 추가 | **아니오** — 새 파일만 | `mcp_servers/korean/*.py` + `agent_config.yaml` 항목 추가 |
| 한국 스킬 추가 | **최소** | `skills/korean/*/SKILL.md` (자동 디스커버리) + `registry.py` 선택적 등록 |
| pykrx 데이터 소스 | **예** (최소) | `src/data_client/registry.py`에 1개 항목 추가, `config.yaml` 프로바이더 체인에 추가 |
| DART/ECOS 도구 | **아니오** — 새 파일만 | `src/tools/korean/` 네이티브 도구 또는 MCP 서버로 |
| pyproject.toml 의존성 | **예** | `[project.dependencies]` 또는 `[project.optional-dependencies]`에 pykrx, OpenDartReader, ecos 추가 |
| agent_config.yaml | **예** | `mcp.servers` 배열에 한국 서버 항목 추가 |
