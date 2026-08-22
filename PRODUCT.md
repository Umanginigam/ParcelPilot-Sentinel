# ParcelPilot Sentinel — Product Note

## 1. Additional Client Problem

I chose to address a proactive operations problem in addition to reactive
customer support.

Instead of waiting for customers to report failures, the system identifies
operational risks such as:

- SLA breaches
- approaching SLA deadlines
- repeated issues across accounts
- known product issues
- high-severity incidents

This is exposed through an internal Ops view.

The goal is to help support teams identify problems before they become a
larger customer-impacting incident.

---

## 2. What Else I Would Build

If this were developed beyond the assessment, I would prioritize:

### Durable production state

Replace the in-memory checkpointer with a durable shared checkpointer so
agent conversations and pending confirmations survive restarts.

### Production observability

Add:

- structured logs
- distributed tracing
- latency metrics
- tool success/failure rates
- LLM token/cost tracking
- escalation rates

### Better retrieval

BM25 is intentionally simple for this submission.

A production system could combine lexical retrieval with embeddings and
reranking while retaining the deterministic authority layer.

### Feedback loop

Allow support agents to mark answers as:

- correct
- incorrect
- needs review

This could create an evaluation dataset for improving retrieval and agent
behavior.

### Incident workflow integration

Connect confirmed escalations to the company's actual incident/ticketing
system instead of the current local JSONL persistence.

---

## 3. What I Intentionally Left Out

I intentionally did not build:

- a production authentication provider
- a production database
- distributed durable agent state
- real ticketing/incident-system integration
- a sophisticated vector database
- autonomous state-changing actions
- a large-scale evaluation infrastructure
- multi-region deployment

These would add production complexity without materially improving the core
assessment objective.

The submission instead focuses on correctness, authorization, evidence,
conflict handling, and controlled actions.

---

## 4. Product Success Metric

The primary metric I would use is:

> **Support Resolution Accuracy**

Specifically:

**Percentage of support questions where the agent's final resolution matches
the authoritative policy decision and requires no human correction.**

I would track this alongside escalation rate.

A useful production dashboard would therefore show:

- resolution accuracy
- human correction rate
- escalation rate
- average time to resolution
- average response latency

Accuracy is the most important metric because a fast support agent that gives
incorrect policy decisions is worse than a slower agent that correctly knows
when to escalate.