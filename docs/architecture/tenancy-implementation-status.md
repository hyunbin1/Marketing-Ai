# 멀티테넌시/메모리 구현 현황 (Implementation Status & Handoff)

> 이 문서는 세션이 바뀌어도(원격 ↔ 로컬 Claude) 작업을 이어받기 위한 **단일 인수인계 지점**이다. 새 세션은 최신 `main`을 pull하고 이 문서 + 아래 설계 문서만 읽으면 맥락을 잡을 수 있다. 대화 히스토리를 옮길 필요 없음.

## 설계 근거 (먼저 읽을 것)
- [`multitenancy-design.html`](multitenancy-design.html) — 6계층 테넌트 격리 설계
- [`memory-langgraph-design.html`](memory-langgraph-design.html) — 대화 메모리(LangGraph) 설계

## 전체 계획 (의존순)
0. **ES 인증** — 완료 ✅
1. **RLS 격리 스파인** (1a 마이그레이션 + 1b 활성화) — **코드 완료, DB 검증 대기** ⏳
2. JWT + refresh 표준화 — 미착수
3. 메모리 (turns/summaries + LangGraph 체크포인터 + compaction) — 미착수
4. 감사 로그 + 봉투 암호화(KEK/DEK) — 미착수 (감사는 미들웨어 AOP + 도메인 명시 호출 하이브리드)

## 지금까지 한 것 (main 커밋)
- **step 0** `feat(security): authenticate non-local Elasticsearch connections`
  - `ELASTICSEARCH_URL`이 비-로컬인데 `ELASTICSEARCH_API_KEY` 없으면 기동 거부(fail-closed). 클라이언트 API키/TLS 지원.
- **step 1a** `feat(security): tenant-isolation RLS migration + app_user role`
  - 마이그레이션 v5(`persistence/postgres.py`): 5개 테넌트 테이블 `workspace_id` 백필 + 7개 테이블 RLS 정책(USING/WITH CHECK, `current_setting('app.workspace_id')`) + `app_user` 롤(NOSUPERUSER·NOBYPASSRLS) 생성·권한.
  - 비파괴적: 앱은 아직 슈퍼유저라 RLS 우회 → 동작 변화 없음.
- **step 1b** `feat(security): activate tenant RLS via app_user connection + request context`
  - `persistence/tenant.py`: 요청 스코프 `tenant_context(workspace_id)` (ContextVar).
  - `PostgresDatabase(set_tenant_guc=, run_migrations=)`: 커넥션마다 `set_config('app.workspace_id', …, is_local=true)`.
  - `wiring.py`: **관리 스토어**(superuser: 마이그레이션·시드·auth 조회, RLS 우회) vs **앱 스토어**(`app_user`, RLS 적용). 에이전트 검색/문서 리포지토리를 앱 스토어로 라우팅.
  - `http_scope.authorized_campaign_scope`: 캠페인→회사를 관리 커넥션으로 해석 후 요청 전체를 `tenant_context`로 감쌈. `analysis/use_case.handle`도 동일.
  - `config.py`: `APP_DATABASE_URL` 추가.

## 핵심 설계 결정 / 함정 (반드시 인지)
- **슈퍼유저는 RLS를 항상 우회한다.** dev의 `launchpilot` 계정이 슈퍼유저라, RLS가 실제로 걸리려면 앱이 **`app_user`(비-슈퍼유저)로 접속**해야 한다. → `APP_DATABASE_URL` 필수.
- **안전 기본값**: `APP_DATABASE_URL` 미설정 시 앱 스토어가 관리 URL로 폴백 → **강제 비활성 = 기존과 동일 동작**. 켜는 건 그 값을 지정할 때뿐.
- **auth 부트스트랩**: "이 캠페인이 어느 회사?"는 RLS 걸린 상태에선 못 읽으므로, 인증/스코프 해석 읽기는 **관리(superuser) 커넥션**으로. 스코프 확정 후 도메인 읽기만 `app_user` + GUC.
- **fail-closed**: GUC 미설정 시 정책이 0건 반환. 그래서 도메인 요청은 반드시 `tenant_context` 안에서 실행.
- 신원 테이블(users/workspaces/memberships)·`platform_connections`는 이번 격리 축에서 제외(후속).

## 검증 방법 (로컬, Postgres 필요)
```bash
cd services/launchpilot-api
docker compose up -d postgres
uv sync --extra dev
# 1a 구조 + 1b 동작(RLS) 검증
uv run pytest tests/test_tenant_isolation.py tests/test_tenant_isolation_enforcement.py -q
# 회귀 확인(참고: tests/test_marketing_golden_v2.py 는 사전존재 SyntaxError로 collection 에러 — 본 작업과 무관)
```
- dev에서 강제 실제 활성화: `.env`에 `APP_DATABASE_URL=postgresql://app_user:app-user-local@127.0.0.1:5432/launchpilot` 추가 후 앱 재시작.
- `app_user` dev 계정은 `docker/postgres/init-test-db.sql`이 새 볼륨에서 생성. 기존 볼륨이면 수동:
  `ALTER ROLE app_user LOGIN PASSWORD 'app-user-local' NOSUPERUSER NOBYPASSRLS;`

## 다음 세션이 할 일
1. 위 검증 명령으로 1을 **실제 DB에서 green** 확인. 실패 시 마이그레이션/GUC 배선부터 디버그.
2. 통과하면 step 2(JWT) 또는 step 3(메모리)로. 권장 순서는 0→1→2→3→4.
