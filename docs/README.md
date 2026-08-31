# 📚 LaunchPilot 공식 엔지니어링 문서 허브 (Documentation Hub)

마케팅 도메인 특화 인과 분석 AI 에이전트 **LaunchPilot**의 아키텍처, 실측 벤치마크 보고서, 아키텍처 결정서(ADR) 및 공식 PR 문서를 모아둔 단일 진실 공급원(Single Source of Truth) 허브입니다.

---

## 🧭 문서 디렉토리 구조 (Directory Layout)

```text
docs/
├── README.md                           # 🧭 전체 문서 내비게이션 허브 (본 문서)
├── pull-request.md                     # 🚀 공식 PR 본문 (PR Description Master)
│
├── architecture/                       # 🏛️ 시스템 설계 및 아키텍처
│   ├── system-architecture.md          # • LangGraph 4계층 순환 인지 토폴로지 (C3 다이어그램)
│   ├── multitenancy-design.md          # 🔐 멀티테넌시 6계층 상세 설계 (To-Be)
│   ├── memory-langgraph-design.md      # 🧠 대화 메모리 · LangGraph 심화 설계 (To-Be)
│   └── adr/                            # • 아키텍처 결정서 (Architecture Decision Records)
│       ├── 0001-retrieval-storage-strategy.md
│       ├── 0002-source-of-truth-database.md
│       ├── 0003-feature-oriented-modular-monolith.md
│       ├── 0004-chunking-strategy.md
│       ├── 0005-reranking-strategy.md
│       ├── 0006-routing-strategy.md
│       └── 0007-elimination-of-intent-parser-in-preprocessing.md
│
└── reports/                            # 📊 실측 실험 및 벤치마크 보고서
    ├── master-engineering-report.md    # 📘 [마스터 결산서] V1~V3 데이터셋, 3단계 어블레이션, N=20 실측, 최적화
    └── dataset-evolution.md            # 🧪 V1 ➔ V2 ➔ V3 데이터셋 진화 및 적대적 감사 아키텍처
```

---

## 📌 핵심 문서 바로가기

| 카테고리 | 핵심 문서 | 주요 내용 |
| :--- | :--- | :--- |
| **🚀 Pull Request** | [docs/pull-request.md](pull-request.md) | V3 데이터셋 및 LangGraph 인-루프 파이프라인 완성 공식 PR 본문 |
| **📘 마스터 결산서** | [docs/reports/master-engineering-report.md](reports/master-engineering-report.md) | 데이터셋 진화, 3단계 어블레이션, N=20 실측, 지연시간 83.4% 최적화 총결산 |
| **🏛️ 시스템 아키텍처** | [docs/architecture/system-architecture.md](architecture/system-architecture.md) | 전처리 ➔ 본체 에이전트 ➔ 도구 ➔ 인-루프 리랭커 순환 토폴로지 |
| **🔐 멀티테넌시 설계** | [docs/architecture/multitenancy-design.md](architecture/multitenancy-design.md) | `workspace_id` 배턴을 6계층에 관통시키는 테넌트 격리 To-Be 설계 (JWT·RLS·감사) |
| **🧠 메모리 · LangGraph** | [docs/architecture/memory-langgraph-design.md](architecture/memory-langgraph-design.md) | 체크포인터·요약(compaction)·RLS 격리로 "이어지는 대화"를 만드는 심화 설계 |
| **🧪 데이터셋 진화** | [docs/reports/dataset-evolution.md](reports/dataset-evolution.md) | 30개 캠페인, 1,050개 코퍼스, 150건 무편향 블라인드 질의 설계 |
| **📝 아키텍처 결정서** | [docs/architecture/adr/](architecture/adr/) | ADR 0001 ~ ADR 0007 핵심 설계 의사결정 기록 |

---

## 🏛️ 확정된 LangGraph 순환 인지 토폴로지

```mermaid
flowchart TD
    START --> Router["1. [전처리 계층]<br/>ScopeRouter: 세션 캠페인/시간 앵커링 (0초, 비파괴적 - ADR 0007)"]
    Router --> Agent["2. [본 에이전트 인지 본체]<br/>AgentNode: Gemini 3.7 Flash 기반 도구 자율 융합"]
    
    subgraph CognitiveLoop ["🔄 인-루프 탐색 & 원샷 정제 사이클"]
        Agent -->|다중 쿼리 배치 호출| Tools["3. [도구 실행 노드]<br/>ToolNode: Causal Graph / SQL / BM25 / Dense (병렬 실행)"]
        Tools --> Reranker["4. [자료 정리 노드]<br/>EvidenceOrganizerNode: 다중 턴 인출 자료 원샷 글로벌 정렬 (3.09s ⚡)"]
        Reranker --> Agent
    end
    
    Agent -->|100% 팩트 완결 시| END["5. [최종 생성]<br/>[surface | UUID | timestamp] 완벽 인용 답변"]
```
