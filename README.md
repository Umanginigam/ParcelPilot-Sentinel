# ParcelPilot Sentinel

An evidence-backed support agent with authority-aware policy resolution, scoped data access, human-in-the-loop escalation, and a proactive operations view.

The core design keeps the LLM probabilistic where language understanding is needed, and keeps policy decisions, authorization, and state-changing actions deterministic and guarded.

> **The architectural thesis:** the LLM proposes, deterministic tools decide, authorization is enforced in code, and state-changing actions require explicit human confirmation.

**Status:** Steps 2–9 complete · deployment pending · **40 tests passing**

---

## Quickstart

```bash
pip install -r requirements.txt
python build_data.py        # Excel → SQLite, PDFs → searchable sections
pytest -q                   # 40 passed — no API key required
```

Add a `.env` for live model calls:

```bash
GROQ_API_KEY=your_key_here
```

The LLM layer is provider-agnostic behind an `LLM` protocol, so the full agent — including the confirmation gate — is testable with `StubLLM` and no API key.

**Backend** — `uvicorn api:app --reload` → `http://127.0.0.1:8000` (health check at `/health`)

**Frontend** — from the frontend directory: `npm install && npm run dev`

---

## Architecture

```
┌──────────────────────────────────────────┐
│              Next.js UI                  │
│  Case desk · Evidence · Trace · Ops      │
└───────────────────┬──────────────────────┘
                    │  REST / JSON
┌───────────────────▼──────────────────────┐
│                FastAPI                   │
│      /chat   /confirm   /ops/alerts      │
└───────────────────┬──────────────────────┘
                    │
┌───────────────────▼──────────────────────┐
│           LangGraph orchestration        │
│    routing · interrupt · resume · trace  │
└───────────────────┬──────────────────────┘
                    │
      ┌─────────────┼─────────────┐
      ▼             ▼             ▼
  Read tools   Resolution     Action tool
      │          engine            │
      ▼             ▼              ▼
  SQLite +     Authority      Confirmation
   BM25          rules            gate
      └─────────────┼──────────────┘
                    ▼
            Evidence + trace
```

### Module map

| Layer | File | Responsibility |
|---|---|---|
| Data | `src/db.py` | Excel → SQLite; typed, scope-free row accessors |
| Access | `src/auth.py`, `src/tools.py` | Auth context, scoped reads, guarded actions |
| Retrieval | `src/retriever.py` | PDF → sections → BM25, behind a `Retriever` interface |
| Decisions | `src/resolution_engine.py` | Authority + conflict engine; deterministic rulings |
| Agent | `src/agent.py` | LangGraph loop, tool routing, confirmation interrupt |
| Model | `src/llm.py` | `LLM` protocol + Groq implementation + `StubLLM` |
| API | `api.py` | Chat, confirmation, evidence, and Ops endpoints |
| Proactive | `src/proactive.py` | SLA scanning, clustering, high-severity detection |
| Config | `src/registry.py`, `src/config.py` | Source metadata, account policy, snapshot clock |
| UI | Next.js frontend | Case desk, trace, evidence, confirmation, Ops view |

---

## Design principles

### 1. Retrieval owns topic; the engine owns authority

BM25 retrieves passages relevant to the question. It does **not** decide which document governs. The resolution engine determines freshness, applicability, account scope, precedence, conflicts, and escalation requirements.

This separation prevents retrieval ranking from accidentally becoming policy authority — a highly similar deprecated policy should never outrank an applicable current agreement.

### 2. Freshness is explicit

Deprecated sources remain retrievable but are tagged `context_only=true`. They can supply historical context but can never become the governing basis of a ruling.

### 3. Customer agreements override global policy

An account-specific agreement overrides the global SOP **for the dimension it actually addresses**. Where the agreement is silent, the system falls back to the applicable SOP.

### 4. Authorization is enforced in code

Access control never depends on the LLM following instructions. The `AuthContext` is passed into every tool handler:

```python
ctx.assert_can_read_account(order["account_id"])
```

A customer scoped to `ACCT-002` cannot retrieve an order belonging to `ACCT-001`, and a prompt injection cannot widen that scope.

### 5. Historical tickets are context, not authority

Past resolutions can be wrong. `TKT-450` claims a ₹250 cancellation fee applied to Northstar; the signed agreement contradicts it. The system surfaces this under `historical_conflicts` rather than letting it influence the ruling.

---

## Deterministic resolution

The LLM does not determine policy outcomes. For policy questions the agent calls resolver tools — `resolve_cancellation`, `resolve_service_credit`, `resolve_sla` — which return structured rulings:

```json
{
  "answer": "No cancellation fee applies.",
  "rule_applied": "Customer agreement overrides SOP",
  "sources_used": ["05_Northstar_Logistics_Enterprise_Agreement.pdf"],
  "sources_overridden": ["03_Cancellation_and_Service_Credit_SOP_v4.pdf"],
  "historical_conflicts": ["TKT-450 claimed INR 250 fee — contradicted"],
  "confidence": "high",
  "escalate": false
}
```

The LLM's only job is turning that ruling into natural language.

---

## Human-in-the-loop escalation

State-changing actions are never executed directly by the model:

1. The LLM proposes the action
2. `prepare_escalation()` builds a preview — **no write**
3. LangGraph `interrupt()` suspends the graph
4. The user sees the preview and decides
5. **Reject** → cancelled, no write · **Confirm** → `commit_escalation()` runs

Incidents affecting all users are recorded against `account_id = GLOBAL`.

---

## Evidence and decision metadata

The API aggregates resolver metadata into an `evidence` block, which the frontend renders as a **chain of authority**:

| Position | Meaning | Example |
|---|---|---|
| **Governs** | The source that decided the outcome | Northstar Agreement |
| **Overridden** | Considered, but outranked | Cancellation SOP v4 |
| **Ignored** | Conflicting history, deliberately excluded | TKT-450 |

Aggregation is conservative: the lowest confidence across a multi-step turn wins, and any escalating sub-ruling escalates the whole answer. This makes the reasoning auditable rather than presenting an opaque LLM answer.

---

## Proven scenarios

| Scenario | Input | Result | Governing reason |
|---|---|---|---|
| Northstar cancellation | `ORD-1001`, BOOKED, +120 min | **₹0 fee** | Agreement overrides SOP's ₹250 |
| LumenWorks credit | `ORD-2002`, 4.5 h delay | **₹300 credit** | 4 h threshold + fixed amount per agreement |
| Standard cancellation | `ORD-3001`, BOOKED, +15 min | **₹0 fee** | SOP v4 — free within 30 min |
| Cross-account access | `ACCT-002` requests `ORD-1001` | **`access_denied`** | Enforced in the tool layer |
| Global outage | All shipment creation failing | **P1 escalation** | Requires explicit confirmation |

The third row matters as much as the first: with no agreement in play the SOP governs and nothing is overridden, proving the rule generalizes rather than always waiving fees.

---

## Proactive Ops view

Internal users can call `GET /ops/alerts` for SLA breaches, approaching deadlines, issue clusters, multi-account incidents, known-issue correlation, and high-severity incidents. Customer contexts are refused.

SLA elapsed time respects each target's basis — 24×7 clock versus business hours — so weekend tickets on business-hours SLAs don't raise false alarms.

---

## Testing

```bash
pytest -q     # 40 passed
```

Golden, agent, and API tests all run deterministically without an LLM API key; live model behavior is verified separately.

**Coverage:** authority precedence · deprecated-policy traps · historical conflicts · cancellation, service-credit, and SLA resolution · escalation classification · account authorization · document scoping · agent routing · tool execution · human confirmation · rejected actions · API responses · evidence aggregation · decision metadata · proactive Ops · LLM error handling

---

## Project status

| Area | Status |
|---|:--:|
| Data ingestion · SQLite layer | ✅ |
| Authorization · document scoping | ✅ |
| BM25 retrieval · authority engine | ✅ |
| Golden tests · end-to-end tests | ✅ |
| LangGraph agent · human confirmation | ✅ |
| LLM integration | ✅ |
| FastAPI · evidence API · proactive Ops | ✅ |
| Next.js UI | ✅ |
| Deployment | ⏳ |# ParcelPilot Sentinel

An evidence-backed support agent with authority-aware policy resolution, scoped data access, human-in-the-loop escalation, and a proactive operations view.

The core design keeps the LLM probabilistic where language understanding is needed, and keeps policy decisions, authorization, and state-changing actions deterministic and guarded.

> **The architectural thesis:** the LLM proposes, deterministic tools decide, authorization is enforced in code, and state-changing actions require explicit human confirmation.

**Status:** Steps 2–9 complete · deployment pending · **40 tests passing**

---

## Quickstart

```bash
pip install -r requirements.txt
python build_data.py        # Excel → SQLite, PDFs → searchable sections
pytest -q                   # 40 passed — no API key required
```

Add a `.env` for live model calls:

```bash
GROQ_API_KEY=your_key_here
```

The LLM layer is provider-agnostic behind an `LLM` protocol, so the full agent — including the confirmation gate — is testable with `StubLLM` and no API key.

**Backend** — `uvicorn api:app --reload` → `http://127.0.0.1:8000` (health check at `/health`)

**Frontend** — from the frontend directory: `npm install && npm run dev`

---

## Architecture

```
┌──────────────────────────────────────────┐
│              Next.js UI                  │
│  Case desk · Evidence · Trace · Ops      │
└───────────────────┬──────────────────────┘
                    │  REST / JSON
┌───────────────────▼──────────────────────┐
│                FastAPI                   │
│      /chat   /confirm   /ops/alerts      │
└───────────────────┬──────────────────────┘
                    │
┌───────────────────▼──────────────────────┐
│           LangGraph orchestration        │
│    routing · interrupt · resume · trace  │
└───────────────────┬──────────────────────┘
                    │
      ┌─────────────┼─────────────┐
      ▼             ▼             ▼
  Read tools   Resolution     Action tool
      │          engine            │
      ▼             ▼              ▼
  SQLite +     Authority      Confirmation
   BM25          rules            gate
      └─────────────┼──────────────┘
                    ▼
            Evidence + trace
```

### Module map

| Layer | File | Responsibility |
|---|---|---|
| Data | `src/db.py` | Excel → SQLite; typed, scope-free row accessors |
| Access | `src/auth.py`, `src/tools.py` | Auth context, scoped reads, guarded actions |
| Retrieval | `src/retriever.py` | PDF → sections → BM25, behind a `Retriever` interface |
| Decisions | `src/resolution_engine.py` | Authority + conflict engine; deterministic rulings |
| Agent | `src/agent.py` | LangGraph loop, tool routing, confirmation interrupt |
| Model | `src/llm.py` | `LLM` protocol + Groq implementation + `StubLLM` |
| API | `api.py` | Chat, confirmation, evidence, and Ops endpoints |
| Proactive | `src/proactive.py` | SLA scanning, clustering, high-severity detection |
| Config | `src/registry.py`, `src/config.py` | Source metadata, account policy, snapshot clock |
| UI | Next.js frontend | Case desk, trace, evidence, confirmation, Ops view |

---

## Design principles

### 1. Retrieval owns topic; the engine owns authority

BM25 retrieves passages relevant to the question. It does **not** decide which document governs. The resolution engine determines freshness, applicability, account scope, precedence, conflicts, and escalation requirements.

This separation prevents retrieval ranking from accidentally becoming policy authority — a highly similar deprecated policy should never outrank an applicable current agreement.

### 2. Freshness is explicit

Deprecated sources remain retrievable but are tagged `context_only=true`. They can supply historical context but can never become the governing basis of a ruling.

### 3. Customer agreements override global policy

An account-specific agreement overrides the global SOP **for the dimension it actually addresses**. Where the agreement is silent, the system falls back to the applicable SOP.

### 4. Authorization is enforced in code

Access control never depends on the LLM following instructions. The `AuthContext` is passed into every tool handler:

```python
ctx.assert_can_read_account(order["account_id"])
```

A customer scoped to `ACCT-002` cannot retrieve an order belonging to `ACCT-001`, and a prompt injection cannot widen that scope.

### 5. Historical tickets are context, not authority

Past resolutions can be wrong. `TKT-450` claims a ₹250 cancellation fee applied to Northstar; the signed agreement contradicts it. The system surfaces this under `historical_conflicts` rather than letting it influence the ruling.

---

## Deterministic resolution

The LLM does not determine policy outcomes. For policy questions the agent calls resolver tools — `resolve_cancellation`, `resolve_service_credit`, `resolve_sla` — which return structured rulings:

```json
{
  "answer": "No cancellation fee applies.",
  "rule_applied": "Customer agreement overrides SOP",
  "sources_used": ["05_Northstar_Logistics_Enterprise_Agreement.pdf"],
  "sources_overridden": ["03_Cancellation_and_Service_Credit_SOP_v4.pdf"],
  "historical_conflicts": ["TKT-450 claimed INR 250 fee — contradicted"],
  "confidence": "high",
  "escalate": false
}
```

The LLM's only job is turning that ruling into natural language.

---

## Human-in-the-loop escalation

State-changing actions are never executed directly by the model:

1. The LLM proposes the action
2. `prepare_escalation()` builds a preview — **no write**
3. LangGraph `interrupt()` suspends the graph
4. The user sees the preview and decides
5. **Reject** → cancelled, no write · **Confirm** → `commit_escalation()` runs

Incidents affecting all users are recorded against `account_id = GLOBAL`.

---

## Evidence and decision metadata

The API aggregates resolver metadata into an `evidence` block, which the frontend renders as a **chain of authority**:

| Position | Meaning | Example |
|---|---|---|
| **Governs** | The source that decided the outcome | Northstar Agreement |
| **Overridden** | Considered, but outranked | Cancellation SOP v4 |
| **Ignored** | Conflicting history, deliberately excluded | TKT-450 |

Aggregation is conservative: the lowest confidence across a multi-step turn wins, and any escalating sub-ruling escalates the whole answer. This makes the reasoning auditable rather than presenting an opaque LLM answer.

---

## Proven scenarios

| Scenario | Input | Result | Governing reason |
|---|---|---|---|
| Northstar cancellation | `ORD-1001`, BOOKED, +120 min | **₹0 fee** | Agreement overrides SOP's ₹250 |
| LumenWorks credit | `ORD-2002`, 4.5 h delay | **₹300 credit** | 4 h threshold + fixed amount per agreement |
| Standard cancellation | `ORD-3001`, BOOKED, +15 min | **₹0 fee** | SOP v4 — free within 30 min |
| Cross-account access | `ACCT-002` requests `ORD-1001` | **`access_denied`** | Enforced in the tool layer |
| Global outage | All shipment creation failing | **P1 escalation** | Requires explicit confirmation |

The third row matters as much as the first: with no agreement in play the SOP governs and nothing is overridden, proving the rule generalizes rather than always waiving fees.

---

## Proactive Ops view

Internal users can call `GET /ops/alerts` for SLA breaches, approaching deadlines, issue clusters, multi-account incidents, known-issue correlation, and high-severity incidents. Customer contexts are refused.

SLA elapsed time respects each target's basis — 24×7 clock versus business hours — so weekend tickets on business-hours SLAs don't raise false alarms.

---

## Testing

```bash
pytest -q     # 40 passed
```

Golden, agent, and API tests all run deterministically without an LLM API key; live model behavior is verified separately.

**Coverage:** authority precedence · deprecated-policy traps · historical conflicts · cancellation, service-credit, and SLA resolution · escalation classification · account authorization · document scoping · agent routing · tool execution · human confirmation · rejected actions · API responses · evidence aggregation · decision metadata · proactive Ops · LLM error handling

---

## Project status

| Area | Status |
|---|:--:|
| Data ingestion · SQLite layer | ✅ |
| Authorization · document scoping | ✅ |
| BM25 retrieval · authority engine | ✅ |
| Golden tests · end-to-end tests | ✅ |
| LangGraph agent · human confirmation | ✅ |
| LLM integration | ✅ |
| FastAPI · evidence API · proactive Ops | ✅ |
| Next.js UI | ✅ |
| Deployment | ⏳ |