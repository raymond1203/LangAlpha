# 포크 프로젝트 가이드

> 이 파일은 루트 `CLAUDE.md`(업스트림 원본)를 보완한다. 둘 다 자동 로드된다.
> 상세 분석은 `.claude/docs/` 참조.

## 이 포크의 목적

`ginlix-ai/LangAlpha`(Apache 2.0) 포크. **한국 시장 데이터 레이어 + 스킬** 추가, **단일 사용자 Docker 셀프호스팅** 최적화.

## 커스텀 코드 경로 컨벤션

| 영역 | 경로 | 비고 |
|------|------|------|
| 한국 MCP 서버 | `mcp_servers/korean/` | FastMCP 패턴 준수 |
| 한국 스킬 | `skills/korean/{skill-name}/SKILL.md` | 파일시스템 디스커버리 자동 감지 |
| 한국 Data Source | `src/data_client/korean/` | MarketDataSource Protocol 구현 |
| 한국 네이티브 도구 | `src/tools/korean/` | LangChain BaseTool |
| 한국 테스트 | `tests/unit/mcp_servers/korean/` 등 | 기존 테스트 패턴 답습 |
| 포크 문서 | `.claude/docs/` | CODEBASE_MAP, ROADMAP 등 |

## 코드 수정 규칙

1. **새 파일/모듈 추가를 우선**한다. 업스트림 파일 수정은 최소화.
2. 업스트림 파일을 수정할 때는 반드시 **`# FORK: 설명`** 주석을 변경 지점에 추가한다.
3. `agent_config.yaml`, `config.yaml` 수정 시 기존 항목 아래 끝부분에 추가하여 머지 충돌을 최소화한다.
4. 보안 관련 코드(암호화, credential redaction, 보호 경로 가드)는 수정하지 않는다.
5. 루트 `CLAUDE.md`는 **업스트림 원본을 유지**한다. 포크 가이드는 이 파일(`.claude/CLAUDE.md`)에만 작성.

## GitHub 워크플로우

모든 GitHub 활동(Issue, 커밋, PR, 리뷰)은 **한국어**로 작성한다.

### 워크플로우 순서
1. Issue 생성 → Issue 코멘트에 판단 과정 기록 (코드 작성 전)
2. `git checkout -b feature/#이슈번호-설명` (main에서 분기, main 직접 커밋 금지)
3. 코드 작성 → `pytest` + `ruff check` 통과 확인 → 커밋
4. `gh pr create` (PR 본문 템플릿 준수)
5. CodeRabbit 리뷰 확인 → PR 코멘트에 선별 사유 기록 → fix 커밋 반영
6. 머지 → main 복귀 → 로컬/리모트 브랜치 삭제

### 커밋 규칙
- Conventional Commits: `feat: 설명`, `fix: 설명`, `refactor: 설명`
- 하나의 커밋 = 하나의 논리적 변경
- 커밋 메시지에 "무엇을 왜 변경했는지" 포함

### 브랜치명
- `feature/#이슈번호-설명`, `fix/#이슈번호-설명`

### PR 본문 템플릿
```
## 요약
Closes #이슈번호
한 줄 요약.

## 변경 사항
- 파일별 변경 내용

## 기술적 판단
- 왜 이 방식을 선택했는지, 대안은 무엇이었는지

## 검증
- 테스트 결과, 수동 검증 내용
```

### 금지 문구
아래 AI 생성 표시를 커밋 메시지, PR 본문, 코드 주석 등에 **절대 작성하지 않는다**:
- `Co-Authored-By: Claude ...`
- `Generated with [Claude Code](...)`
- 기타 AI 도구 사용을 드러내는 서명/태그

## 디렉토리 책임 요약

| 디렉토리 | 책임 |
|----------|------|
| `mcp_servers/` | FastMCP 데이터 도구 서버 (stdio subprocess, 55개 도구) |
| `mcp_servers/korean/` | **[FORK]** 한국 시장 MCP 서버 (pykrx, DART, ECOS) |
| `skills/` | 에이전트 스킬 (SKILL.md 기반, 28개) |
| `skills/korean/` | **[FORK]** 한국 시장 분석 스킬 |
| `src/ptc_agent/` | 에이전트 코어: 팩토리, 미들웨어, MCP 연결, 세션 |
| `src/server/` | FastAPI 앱, 24개 라우터, 핸들러, 서비스 |
| `src/tools/` | LangChain 네이티브 도구 (검색, 시장 데이터, SEC) |
| `src/data_client/` | 시장 데이터 프로바이더 추상화 + fallback chain |
| `src/llms/` | LLM 프로바이더 래퍼, 모델 매니페스트 |
| `src/config/` | 인프라 설정, 환경변수 |
| `src/utils/` | Redis 캐시, 스토리지, 트래킹 |

## 자주 쓸 작업 레시피

### 새 MCP 서버 추가 (5단계)

1. `mcp_servers/korean/{서버명}_mcp_server.py` 작성
   - `from mcp.server.fastmcp import FastMCP` 임포트
   - `mcp = FastMCP("서버이름MCP")` 인스턴스 생성
   - `@mcp.tool()` 데코레이터로 도구 등록
   - `if __name__ == "__main__": mcp.run(transport="stdio")` 진입점
2. `pyproject.toml`에 필요한 의존성 추가 (예: `pykrx>=1.0.45`)
3. `agent_config.yaml`의 `mcp.servers` 배열 끝에 서버 항목 추가:
   ```yaml
   # FORK: 한국 시장 서버
   - name: "kr_price"
     enabled: true
     command: "uv"
     args: ["run", "python", "mcp_servers/korean/kr_price_mcp_server.py"]
     env: {}
     tool_exposure_mode: "detailed"
   ```
4. `tests/unit/mcp_servers/korean/test_{서버명}_mcp.py` 단위 테스트 작성
5. `uv sync && uv run pytest tests/unit/mcp_servers/korean/ -v` 로 검증

### 새 스킬 추가 (3단계)

1. `skills/korean/{스킬명}/SKILL.md` 작성 (YAML 프론트매터 필수):
   ```yaml
   ---
   name: 스킬명           # 디렉토리명과 일치 (소문자 + 하이픈)
   description: "설명"    # 1-1024자
   ---
   ```
2. 마크다운 본문에 트리거, 워크플로우, 참조 도구 등 작성
3. PTC 모드에서 에이전트가 `Read("skills/korean/{스킬명}/SKILL.md")` 호출하면 자동 로드

### data_client fallback chain에 소스 추가 (4단계)

1. `src/data_client/korean/data_source.py`에 `MarketDataSource` Protocol 구현
2. `src/data_client/registry.py`에 가용성 체크 + 팩토리 함수 추가 (파일 끝, `# FORK:` 주석)
3. `config.yaml`의 `market_data.providers`에 `{name: korean, markets: [kr]}` 추가
4. `tests/unit/data_client/korean/` 에 테스트 작성

## 참고 문서

- `.claude/docs/CODEBASE_MAP.md` — 상세 코드베이스 분석 (MCP 흐름, 미들웨어 스택, BYOK 등)
- `.claude/docs/CUSTOMIZATION_ROADMAP.md` — Phase별 구현 로드맵
- `src/server/CLAUDE.md` — SSE 이벤트 타입, 엔드포인트 상세
