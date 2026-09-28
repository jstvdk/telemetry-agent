# 01 · Problem and rationale

## The problem

Operating an instrument such as a telescope camera produces a steady stream of logs, telemetry, operator commands and configuration changes. A large share of shift work is:

- scanning subsystems for anything out of the ordinary;
- correlating alarms from different sources ("are these three red lines one problem or three?");
- reading tracebacks and searching documentation, chat history and code for the cause;
- writing the shift log and the handover.

This work is repetitive and error-prone at 3 a.m. It also scales with the number of instruments: an array of dozens of telescopes will not get dozens of operators.

**Most expensive moment:** a service fails just before data taking. Today the operator reads the traceback, pastes it into a chatbot that knows nothing about this system, searches the wiki and waits for an expert. The team's knowledge exists, spread across old incidents, fix commits and chat threads, but nobody can search it quickly.

## The proposed product

A **read-only shift assistant** that:
1. watches all sources and detects problems with deterministic rules;
2. keeps one **event timeline** of everything that happened;
3. **explains and correlates** events in plain language, citing event IDs and runbook sections;
4. answers operators' questions ("why did the readout restart at 02:13?");
5. drafts the **shift log**.

**The operator always decides.** The assistant takes over the scanning, correlation and paperwork, and the operator keeps the judgment calls.

## Why an LLM, and where exactly

The hard parts of this job are *language* problems: tracebacks, free-text log messages, runbook prose, chat history, and writing summaries. Rules cannot read a new traceback and connect it to a fix commit from last spring. An LLM can.

The job also contains parts that need *guarantees*, and an LLM cannot give them.

| Give it to the LLM | Keep it in code |
|---|---|
| Read tracebacks and log messages; map them to runbook sections | Detection. A missed alarm is unacceptable, so it has to be a rule |
| Link evidence from different sources into a cause hypothesis | Arithmetic and statistics on time series |
| Write shift logs and handovers | Anything with seconds-level timing |
| Turn an unexpected question into queries | Anything that writes to hardware, software or config |
| Find similar past incidents | Checking that its own claims are true (the validator does that) |

**Rule of thumb:** would you hand the task to a smart new colleague who has read all the documentation but never done a shift, *provided you check the result*? If yes, the LLM can do it. If the task needs a guarantee, write code.

## Design principles

1. **Read-only by construction.** Read-only credentials and no write paths. Never rely on the prompt to prevent actions.
2. **If it can be an if-statement, it is code.**
3. **Features, not raw data.** The LLM sees "slope 0.8 °C/h, 4σ above baseline", never a dump of 10,000 samples.
4. **Grounded or flagged.** Every claim cites evidence; code checks the citations; unverifiable claims are dropped or visibly flagged.
5. **Fail-silent.** If the assistant dies, operations are unaffected. It is never on a critical path.
6. **Verified vs. draft knowledge.** Runbook entries are `verified` or `ai-draft`. Draft knowledge can only be cited with a visible flag.
7. **Pipelines before agents.** Fixed workflows where the steps are known (shift log); one agent loop only where they are not (investigation).
8. **Model-agnostic.** The model is a config value. The evaluation harness is the long-lived asset.
9. **Can run locally.** Production sites may have no internet and strict data policy, so the system must work with a local open-weight model.

## Alternatives considered

| Alternative | Why not (as the main approach) |
|---|---|
| **More dashboards and alarm rules only** | Needed, and built as the deterministic core. But rules cannot explain a new traceback or write a shift log. The rules-only system is also the **fallback** if the LLM layer fails |
| **Chatbot over raw logs (RAG on log lines)** | This is what the v0 spike does. It gives confident wrong answers on counts and trends ([06](06-v0-spike-review.md)), and costs many tokens per question |
| **Fine-tuning a model on our logs** | Little labelled data. The knowledge changes weekly. Weights cannot be reviewed or corrected by an expert, while a runbook in git can |
| **Multi-agent system (one agent per role)** | More failure modes, more cost, harder to evaluate. No evidence yet that one agent with good tools is not enough |
| **Autonomous remediation** | High risk and no track record yet. Revisit only after shadow-mode results and a separate safety review |

## Risks

| Risk | Mitigation |
|---|---|
| Plausible but wrong explanations | Grounding validator; features instead of raw data; shadow mode before advisory mode |
| Alert fatigue | False alerts per shift is a first-class metric; deduplication and digests |
| Prompt injection through log content (logs are untrusted input) | No write tools exist; log text is passed as data; injection scenarios in the test suite |
| Model churn | Provider interface; evaluation harness decides the model, not leaderboards |
| Data policy blocks cloud models | Local model path from day one |

## Framing

It is a **shift assistant**, not "an AI that replaces operators". Report failures next to wins. In operations, a confident wrong answer does more damage than no answer.
