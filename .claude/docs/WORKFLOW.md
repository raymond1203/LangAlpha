# GitHub 워크플로우

GitHub은 사고 과정의 기록이다. 모든 활동(Issue, 커밋, PR, 리뷰)은 **한국어**로 작성한다.
"왜 하는가 → 어떤 판단을 했는가 → 무엇을 했는가 → 어떻게 검증했는가"가 명확히 드러나야 한다.

## 1. Issue 생성 (왜 하는가)
- 모든 작업은 Issue에서 시작한다
- 제목: 명확한 한 줄 요약
- 본문: 배경/문제 상황, 목표, 완료 조건
- 라벨: `feature`, `fix`, `refactor`, `docs`, `chore`
- `gh issue create --title "..." --body "..." --label feature`

## 2. Issue에 판단 과정 기록 (어떤 판단을 했는가)
- **코드 작성 전에** 설계 판단을 Issue 코멘트로 먼저 남긴다
- 작업 중 시도한 것, 선택한 이유, 버린 대안을 기록한다
- 기술적 의사결정이 있으면 근거를 기록한다
- PR 올리기 전에 해당 Issue를 보면 "왜 이렇게 구현했는지" 맥락이 완성되어야 한다
- `gh issue comment <번호> --body "..."`

## 3. 브랜치 생성
- **반드시 main에서 분기** — main에 직접 커밋하지 않는다
- `feature/#이슈번호-설명`, `fix/#이슈번호-설명`
- `git checkout -b feature/#12-rag-pipeline`

## 4. 커밋 (무엇을 했는가)
- Conventional Commits: `feat: 설명`, `fix: 설명`, `refactor: 설명`
- 하나의 커밋 = 하나의 논리적 변경 (커밋 분리 철저)
- 커밋 메시지에 "무엇을 왜 변경했는지" 포함
- 커밋 전 반드시 `pytest` + `ruff check` 통과 확인

## 5. PR 생성 (어떻게 검증했는가)
- `Closes #이슈번호`로 Issue 연결
- PR 본문 템플릿:
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
- `gh pr create --title "..." --body "..."`

## 6. PR 리뷰 → 선별 → fix 커밋
- CodeRabbit 자동 리뷰가 동작한다
- 리뷰 항목을 모두 확인한 뒤, **fix 작업 전에** PR 코멘트로 선별 사유를 남긴다:
  - 반영할 항목: 무엇을 왜 수용하는지
  - 스킵할 항목: 왜 현재 PR에서 반영하지 않는지 (과도한 변경, 범위 초과, 의견 불일치 등)
- 선별 코멘트 작성 후 `fix: 설명` 커밋으로 반영한다
- 현재 PR 범위를 벗어나는 피드백은 별도 Issue로 분리하여 추적한다
- `gh issue create --title "..." --body "PR #번호 리뷰에서 발견: ..." --label fix`

## 7. 머지 → 브랜치 정리
- 셀프 리뷰 완료 후 머지
- `gh pr merge --squash` 또는 `--merge`
- 머지 후 브랜치 정리:
  ```bash
  git checkout main && git pull
  git branch -d feature/#번호-설명                         # 로컬 삭제
  git push origin --delete feature/#번호-설명              # 리모트 삭제
  ```
- main만 남기고 머지 완료된 브랜치는 로컬/리모트 모두 즉시 정리한다

## 작업 순서 요약 (체크리스트)
1. Issue 확인 → Issue 코멘트에 판단 과정 기록
2. `git checkout -b feature/#번호-설명` (main에서 분기)
3. 코드 작성 → `pytest` + `ruff check` 통과 확인 → 커밋
4. `gh pr create` (PR 본문 템플릿 준수)
5. CodeRabbit 리뷰 확인 → PR 코멘트에 선별 사유 기록 → fix 커밋 반영
6. 머지 → main 복귀 → 로컬 브랜치 삭제

## 금지 문구
아래와 같은 AI 생성 표시를 커밋 메시지, PR 본문 등에 절대 작성하지 않는다:
- `Co-Authored-By: Claude ...`
- `Generated with [Claude Code](...)`
- 기타 AI 도구 사용을 드러내는 서명/태그
