# Documentation

This folder records how the project was designed, not just what the code does. Read it in order if you want the reasoning; jump to a file if you want one answer.

| # | Document | Answers |
|---|---|---|
| 00 | [Project journey](00-journey.md) | How did the idea get from a brainstorm to code, and what changed at each step? |
| 01 | [Problem and rationale](01-rationale.md) | What problem is this solving, why use an LLM for it, and what is the LLM *not* allowed to do? |
| 02 | [Requirements and use cases](02-requirements.md) | Who uses it, for what, and what counts as "done"? |
| 03 | [Architecture](03-architecture.md) | Components, data model, tool contracts, and how a question flows through the system |
| — | [Architecture decision records](adr/README.md) | Why each major design choice was made, and what was rejected |
| 04 | [Evaluation](04-evaluation.md) | Metrics, dataset, scoring, and experiments |
| 05 | [Test plan](05-test-plan.md) | Test cases by layer, and what runs in CI |
| 06 | [v0 spike review](06-v0-spike-review.md) | An honest review of the first prototype, with measured defects |
| 07 | [Delivery plan](07-delivery-plan.md) | Milestones, exit criteria, and the demo script |
| — | [**Provenance**](PROVENANCE.md) | Dated log of every step, decision and failure, with evidence |
| — | [**Results**](results.md) | Measured detector numbers on dev and held-out data, with caveats |

**Status legend** used throughout: ✅ implemented · 🔨 in progress · 📐 designed, not built yet.
