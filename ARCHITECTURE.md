# ParcelPilot Sentinel — Architecture Note

## 1. Overview

ParcelPilot Sentinel is an evidence-backed support agent for logistics
operations.

The architecture deliberately separates probabilistic language understanding
from deterministic policy resolution and authorization.

The core principle is:

> The LLM proposes; deterministic tools decide; authorization is enforced in
> code; state-changing actions require explicit human confirmation.

---

## 2. Agent Design

The agent is implemented using LangGraph.

The graph follows this flow:

User request
    ↓
Agent
    ↓
Tool call
    ↓
Read/Resolver tool
    ↓
Tool result
    ↓
Agent
    ↓
Final answer

For state-changing operations:

Agent
    ↓
Write proposal
    ↓
Confirmation node
    ↓
interrupt()
    ↓
Human confirmation
    ↓
commit
    ↓
Agent
    ↓
Final answer

The graph uses a checkpointer so an interrupted action can resume from the
same thread after confirmation.

The LLM layer is provider-agnostic through an LLM protocol. A StubLLM is used
for deterministic tests, while the production implementation uses the
configured LLM provider.

---

## 3. Tool Design

Tools are divided into read/resolution tools and state-changing tools.

Examples:

- lookup_order
- lookup_account
- lookup_ticket
- resolve_cancellation
- resolve_service_credit
- resolve_sla
- classify_escalation
- create_escalation

Authorization is enforced inside the tool layer.

The AuthContext contains the caller's role and account scope.

A customer attempting to access another account's data receives an
AccessDenied error.

This means authorization does not depend on the model following a prompt
instruction.

---

## 4. Document Handling

The supplied PDF documents are converted into searchable sections.

BM25 is used for lexical retrieval.

Retrieval is responsible for finding relevant passages, but retrieval ranking
does not determine policy authority.

The resolution engine determines which source governs the decision.

Deprecated documents remain retrievable for context but are marked
context_only and cannot become the authoritative ruling basis.

---

## 5. Structured Data

The supplied spreadsheet data is converted into SQLite.

Structured tools access orders, accounts, and tickets through the database layer.

The database accessors themselves are scope-free; authorization is applied
by the tool layer using AuthContext.

This keeps data access and authorization responsibilities separate.

---

## 6. Source Reliability and Conflict Handling

The system explicitly models source authority.

The main rules are:

1. Deprecated sources cannot become authoritative.
2. Customer-specific agreements override global policies for the dimensions
   they address.
3. Historical tickets are context, not authority.
4. If an authoritative source is unavailable or the situation cannot be
   confidently resolved, the system can escalate.

The API exposes:

- sources_used
- sources_overridden
- historical_conflicts
- confidence
- escalate
- escalate_reason

This allows the frontend to display a chain of authority rather than only
showing the final LLM response.

---

## 7. Human-in-the-Loop Actions

State-changing actions use a two-phase model.

### Prepare

prepare_escalation() validates the action and generates a preview.

It does not mutate state.

### Confirm

LangGraph pauses using interrupt().

The frontend displays the proposed action.

### Commit

Only after explicit confirmation is commit_escalation() executed.

This prevents an LLM from directly performing a state-changing operation.

---

## 8. API Layer

FastAPI exposes:

- GET /health
- POST /chat
- POST /confirm
- GET /ops/alerts

The /chat endpoint starts a new agent thread.

The /confirm endpoint resumes an interrupted thread with the user's decision.

The API also aggregates evidence and decision metadata into a stable response
shape for the frontend.

---

## 9. Frontend

The frontend is implemented with Next.js.

The main UI contains:

- Chat
- Context switcher
- Account switcher
- Tool trace
- Evidence panel
- Confidence/escalation indicator
- Human confirmation dialog
- Internal Ops view

The evidence panel exposes the reasoning chain instead of hiding it behind
the model response.

---

## 10. Proactive Operations

The Ops view provides:

- SLA breaches
- approaching SLA deadlines
- issue clustering
- known issue correlation
- high-severity incidents

The Ops endpoint is restricted to internal users.

---

## 11. Major Technical Trade-offs

### BM25 instead of embeddings

BM25 provides simple, deterministic lexical retrieval and works well for
policy documents containing identifiers, exact terminology, and operational
phrases.

The trade-off is weaker semantic retrieval compared with modern embedding
models.

### SQLite instead of a production database

SQLite keeps the assessment self-contained and reproducible.

For production, a managed relational database would provide better concurrency,
availability, backup, and operational scalability.

### Deterministic resolution engine

This adds engineering effort compared with asking the LLM to reason directly
over retrieved documents.

The benefit is much stronger correctness and auditability for policy decisions.

### LangGraph

LangGraph adds orchestration complexity, but it provides an explicit execution
graph, state persistence, and interrupt/resume semantics that are valuable for
human-in-the-loop workflows.

### In-memory checkpointing

The current implementation uses MemorySaver for the submission/demo.

A production deployment would use a durable shared checkpointer so interrupted
threads survive process restarts and can operate across multiple instances.