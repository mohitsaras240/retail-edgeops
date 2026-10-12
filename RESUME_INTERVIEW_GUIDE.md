# Retail Edge Autopilot — Resume & Technical Interview Guide

This guide prepares software engineers, SREs, and distributed-systems architects to speak confidently about **Retail Edge Autopilot** in senior technical interviews (e.g. NCR Voyix, Amazon Retail, Target, Walmart Labs).

---

## 1. Resume Bullet Points

### Option A: Distributed Systems / Edge Computing Focus
> * Architected and implemented **Retail Edge Autopilot**, an autonomous edge-reliability platform managing 9 containerized PoS and self-service kiosk microservices across distributed stores, achieving 100% test coverage with 92 automated tests.
> * Engineered an offline transaction persistence engine using SQLite WAL and idempotent background batch ingestion, guaranteeing zero transaction loss during store WAN outages.
> * Designed an explainable multi-signal root-cause diagnosis engine that correlates container exit codes, rolling p95 latency anomalies, and dependency graphs to prevent futile restart loops.

### Option B: SRE / Platform Engineering Focus
> * Built a closed-loop self-healing engine (Observe $\to$ Detect $\to$ Diagnose $\to$ Decide $\to$ Recover $\to$ Verify) with safety allowlists, exponential backoff, and human-in-the-loop approval gates for in-flight checkout protection.
> * Implemented real-time operations console in React 18, TypeScript, and Vite with sub-second polling, audit timelines, and transparent execution provenance tracking.
> * Eliminated cross-store blast radius through store-isolated container boundaries and autonomous load shedding of deferrable workloads under host memory/CPU pressure.

---

## 2. Core Interview Talking Points

### Question 1: "Why not use a standard Kubernetes or K3s setup for edge self-healing?"
**Candidate Answer:**
> "Kubernetes liveness probes only know how to restart containers blindly. In a retail store environment, restarting a Point-of-Sale terminal while a customer is mid-swipe corrupts payment terminal state, doubles authorizations, and creates line churn.
> 
> Furthermore, edge nodes are resource-constrained and frequently lose WAN connectivity to central control planes. Autopilot is purpose-built for retail edge constraints: it knows the difference between a dead container (which can be auto-restarted immediately) and an unhealthy-yet-serving lane (which requires human confirmation). It also coordinates local load shedding—pausing background sync workers under CPU pressure to reserve compute for active checkout lanes."

### Question 2: "How do you guarantee that offline transactions aren't lost or duplicated?"
**Candidate Answer:**
> "We implement a write-ahead persistent local store using SQLite in WAL mode. When a customer checks out, the transaction is synchronously committed to disk in state `PENDING_SYNC` before returning a 201 Created to the terminal.
> 
> A background sync worker continuously pushes batches to the central cloud ingestion endpoint. In the event of network disruption, the worker backs off while transactions continue accumulating locally.
> 
> On the central ingest side, we enforce strict idempotency by keying every event on a client-generated UUID with `INSERT OR IGNORE`. Even if retried requests or network blips cause duplicate deliveries, the central ledger remains deduplicated and returns explicit accepted vs. duplicate metrics."

### Question 3: "Why did you choose an explainable heuristic scoring engine over ML for root-cause diagnosis?"
**Candidate Answer:**
> "In critical edge infrastructure, explainability is a hard requirement. If a self-healing system restarts a register or flags an issue, site reliability engineers need to see the exact supporting evidence: 'Exit code 137, OOM flag set, health probe 503'.
> 
> Black-box ML models are prone to hallucination, require huge amounts of labeled failure telemetry from edge hardware that may not exist in early deployments, and cannot easily provide transparent confidence bounds. Our multi-signal diagnoser scores hypotheses deterministically (0-100) while explicitly generating counter-evidence and actionable next steps."

### Question 4: "What happens if a workload enters a crash loop because an upstream database is down?"
**Candidate Answer:**
> "Standard container orchestrators will restart the crash-looping container indefinitely until backoff limits are reached, burning CPU and exhausting host IOPS.
> 
> Autopilot incorporates dependency graph awareness into the diagnosis phase: before planning a recovery action, it queries the health of same-store dependent services. If an upstream dependency is failing, the engine ranks `dependency_unavailable` as the primary cause and explicitly rejects `restart_workload`. Instead, it halts restarts and escalates immediately to edge support with diagnostic evidence, preventing restart storms."

---

## 3. Architecture Deep-Dive Checklist for Interviewers
- **Observability**: Real vs. Simulated provenance clearly tagged at all layers.
- **Verification**: Actions do not equal resolution; verification requires $N$ consecutive healthy canary cycles.
- **Safety**: Bounded action allowlist, dry-run mode, and immutable append-only JSONL audit logs.
- **Scale**: Multi-store topology with zero cross-store blast radius.
