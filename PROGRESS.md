# PROGRESS

## 완료된 것
- SDD(`SkillFetch.md`) v0.1.0 MVP 구현: `src/skillfetch/` (cli, analyzer, discovery, parser, ranker, security, loader, models, llm)
- CLI: `discover`, `inspect`, `load`, `list`, `clean`
- Claude Code 어댑터: `integrations/claude-code/SKILL.md`
- 테스트 100개 통과 (fixture 기반 fake GitHub + fake LLM, 네트워크 없음), ruff clean
- 실제 GitHub 대상 discovery 수동 확인 (2026-10-10): 비인증 저장소 검색과 사용자 지정 저장소(`anthropics/skills/skills`)에서 20개 SKILL.md를 찾았고 모두 파싱됨. HIGH 차단 0건(오탐 없음)

## 진행 중인 것
- 없음

## 다음 단계
- `OPENAI_API_KEY`(+ 가능하면 `GITHUB_TOKEN`)로 실제 E2E 실행: discover → inspect → load
- 기본 모델 `gpt-5.4-mini`(설치된 openai SDK 3.27.0의 모델 목록에서 확인)가 계정에서 JSON mode로 동작하는지 확인 필요
- Exit Criteria 2: 무관한 스킬 추천이나 불필요한 반복 검색이 있는지 `.skillfetch/logs/skillfetch.jsonl`로 점검
- Exit Criteria 3: 스킬이 도움이 된 사례와 도움이 되지 않은 사례를 각각 기록 → 계속 개발할지 결정

## 미결 결정사항
- 비인증 모드에서는 저장소당 최대 3개 SKILL.md만 평가함(경로에 검색어가 들어간 파일 우선). 대형 컬렉션의 관련 스킬을 놓칠 수 있음 → 실제 사용 후 판단
- `network_transfer` HIGH 규칙은 `curl ... $GITHUB_TOKEN` 같은 정상적인 API 호출도 차단함(오탐 가능) → 실제 사례를 보고 판단

## 주요 결정 (재논의 방지)
- 보안 정책 2단계: HIGH(프롬프트 인젝션, 비밀정보 유출, curl|sh, rm -rf / 등)는 차단하고 MEDIUM은 경고만 함
  - 기각: 엄격 모드(5개 범주 중 하나라도 걸리면 차단). 대부분의 스킬에 bash 예시가 있어 거의 다 차단됨
- 에이전트 승인: TTY에서는 [y/N] 확인, TTY가 아니면 `--yes` 필수. 어댑터 SKILL.md에서 사용자가 채팅으로 명시적으로 승인한 뒤에만 `--yes`를 쓰도록 지시
  - 기각: 사람이 직접 `! skillfetch load`를 실행하는 방식만 허용. 흐름이 끊김
- 저장소: https://github.com/hayden-02055/SkillFetch. `main`에는 직접 푸시하지 않고 `feat/mvp` 브랜치 → PR로 반영
- 라이선스: MIT (SDD 초안의 Apache-2.0에서 변경, 사용자 결정)
- 세션 레이아웃은 `sessions/<id>/<skill-name>/SKILL.md` (SDD에는 `sessions/<id>/SKILL.md`). 한 세션에서 여러 스킬을 덮어쓰지 않고 불러오기 위해 바꿈
- SDD 외에 추가한 것: `llm.py`(analyzer와 ranker가 같이 쓰는 OpenAI 호출), `clean` 명령(수용 기준 "임시 파일을 정리할 수 있다"), `--repo` 옵션(4.2 "사용자가 지정한 저장소 또는 경로"), PyYAML 의존성(frontmatter 파싱)
- `--repo`를 지정해도 analyzer가 `requires_skill=false`로 판단하면 검색하지 않음(On-demand 원칙)
