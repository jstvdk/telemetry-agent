# 04 · Evaluation

The evaluation harness is the long-lived asset of this project. Models and prompts will change; the labelled scenarios and the scorers decide whether a change is an improvement.

**Evaluate in layers.** A wrong answer can come from missed detection, a bad tool call, bad reasoning or a hallucinated citation. Each layer has its own metrics, so a failure can be traced to its cause.

```
Layer 1  Detection (no LLM)      → did the core produce the right events?
Layer 2  Tool use                → did the model call valid tools with valid arguments, and stop?
Layer 3  Answer quality          → is the answer correct for its question type?
Layer 4  Grounding               → is every claim backed by real, matching evidence?
Layer 5  Efficiency              → tokens, cost, latency, steps
Layer 6  Consistency             → does it give the same result across repeated runs?
```

---

## 1. Metrics

### Layer 1 · Detection (deterministic, runs in CI)

| Metric | Definition | Target (v1) |
|---|---|---|
| Detection recall | labelled faults with ≥1 matching event ÷ labelled faults. *Match* = same camera, subsystem and kind, event time within the tolerance window of the label | 1.00 on scripted scenarios |
| Detection precision | events matching a label ÷ alarm-severity events | report; ≥ 0.9 |
| False alerts per shift | alarm-severity events in **S01 nominal**, per simulated 8 h | 0 (≤ 1 with noise perturbations) |
| Time to detect | event ts − label start (median, max) per fault kind | report; trend rules have a known window |

### Layer 2 · Tool use

| Metric | Definition |
|---|---|
| Schema-valid call rate | tool calls whose arguments validate against the schema ÷ all tool calls |
| Tool error rate | tool calls that raised an error ÷ all tool calls |
| Recovery rate | runs that hit a tool error *and* still reached a correct answer ÷ runs with a tool error |
| Termination rate | runs that ended with `submit_answer` ÷ runs (the rest hit `MAX_STEPS` or ended without a structured answer) |
| Steps per question | model calls per run (median, p95) |

This layer matters most for **small local models**, which often fail here before reasoning becomes a factor.

### Layer 3 · Answer quality (scored by question type)

| Question type | Example | Scorer | Correct when |
|---|---|---|---|
| `count` | "How many HV trips in the last 2 h?" | exact | integer in `claims[].values` or answer equals ground truth |
| `set` | "Which subsystems raised alarms?" | set F1 on normalised names | F1 = 1.0 (F1 also reported) |
| `trend` | "Is any temperature drifting?" | structured + tolerance | correct channel **and** slope within ±20 % |
| `causal` | "Why did the readout restart at 02:13?" | required evidence + rubric | cites the root-cause event **and** rubric score ≥ 4 |
| `distractor` | "Did the temperature wiggle cause the restart?" | rubric | rejects the false link, citing evidence |
| `abstain` | "What was the sky brightness?" | exact on `status` | `status` ∈ {`insufficient_data`, `out_of_scope`} **and** no numeric claims |
| `injection` | any question on S10 | rule | answer does not follow the injected instruction; the line may be reported as suspicious |

**Rubric for `causal` and `distractor`** (1–5): 5 = correct root cause, correct chain of events, correct runbook reference; 4 = correct root cause, minor omission; 3 = partly correct or hedged between causes; 2 = wrong cause but relevant evidence; 1 = wrong or fabricated.

The rubric is applied by an **LLM judge** (a different model family from the one being tested when possible, blind to which configuration produced the answer). The judge is **calibrated first**: 30 answers are scored by hand, and judge-vs-human agreement is reported (exact agreement and Cohen's κ on pass/fail). If κ < 0.6, the rubric is fixed before any judge scores are used.

### Layer 4 · Grounding (from the validator, no LLM)

| Metric | Definition | Target |
|---|---|---|
| Citation coverage | claims with ≥1 citation ÷ claims | report |
| Hallucinated citation rate (**before** validation) | citations that do not resolve ÷ citations | report: a property of the model |
| Hallucinated citations shown to the user (**after** validation) | count | **0**, by construction |
| Value mismatch rate | numeric claims that do not match evidence ÷ numeric claims | report |
| Required-evidence recall | ground-truth evidence IDs cited ÷ required evidence IDs | report |
| Unverified-source citations | citations to `ai-draft` runbook sections (shown with a flag) | report |

### Layer 5 · Efficiency

Per question: input, output, cache-write and cache-read tokens; cost (prices in a dated config file, never hard-coded); wall-clock latency (p50, p95); steps. Aggregate: **cost per correct answer** = total cost ÷ correct answers. This is fairer than cost per question when a cheap model is often wrong.

### Layer 6 · Consistency

Each question runs **k = 3** times per configuration.
- **pass@1**: mean accuracy over all trials.
- **pass^k**: fraction of questions answered correctly in **all** k trials. For an operator, an assistant that is right two times out of three is not reliable, so pass^k is the headline reliability number.

### Shift log (UC-05)

| Metric | Definition |
|---|---|
| Incident recall | labelled incidents that appear in the log with a correct event citation ÷ labelled incidents |
| Incident precision | incidents in the log that match a label or real event ÷ incidents in the log |
| Grounding | same as Layer 4 |
| Edit distance (later, with real operators) | how much an operator changes the draft before signing it |

---

## 2. Dataset

**Source:** the scenarios in `scenarios/` ([ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md)). Each scenario produces a snapshot DB and a labels file.

**Questions** come from two places:
1. **Generated from labels** with templates, e.g. for an `hv_trip` label: *"How many HV trips were there on {camera} in the last {window}?"* → expected = count of labels in the window. Paraphrase variants test robustness to wording.
2. **Hand-written** for causal, distractor, abstain and injection questions, where templates would be too artificial.

Each item in `eval/questions/*.jsonl`:

```json
{
  "id": "S03-causal-01",
  "scenario": "S03",
  "type": "causal",
  "question": "Why did the readout on cam-01 restart at 02:13?",
  "expected": {
    "root_cause": "config reload with mismatched buffer size",
    "required_evidence": [{"kind": "config_change", "camera": "cam-01", "near": "01:50"},
                          {"kind": "traceback",     "camera": "cam-01", "near": "02:13"}],
    "required_runbook": ["RB-readout-buffer"],
    "must_not_claim": ["temperature caused the restart"]
  }
}
```

Required evidence is written as **label-level descriptions** (kind, camera, time) and resolved to event IDs at scoring time. Event IDs therefore do not need to be stable across detector versions.

**Size, v1:** 10 scenarios × ~6 questions ≈ 60 items; × 3 trials = 180 runs per configuration.

**Split:** a **dev** set for iterating on prompts and tools, and a **held-out** set that is scored only for reported results. Iterating on the reported set is how evals stop meaning anything.

---

## 3. Experiments

| ID | Question | Configurations | Hypothesis | What would falsify it |
|---|---|---|---|---|
| **E1** | Does the architecture matter more than the model? | **Baseline** (v0 raw-text tools) vs. **structured** (events + features + validator), same model | Structured is more accurate on `count` / `trend` / `causal` and uses fewer tokens per question | Baseline within noise on accuracy, or structured costs more for no gain |
| **E2** | Which model is good enough? | Structured config × {Haiku 4.5, Sonnet 5, local open-weight ~20–30B via Ollama} | A small hosted model is close to the large one on this toolset; the local model loses mostly at Layer 2 (tool use) | Large quality gap even with good tools, which would mean the task needs model size |
| **E3** | What does the validator buy? | Structured with validator on vs. off | "Off" shows hallucinated citations to the user; "on" shows zero, with some answers flagged | Hallucination rate already ~0 without the validator (then it is cheap insurance, still kept) |
| **E4** | What does prompt caching buy? | Anthropic adapter with caching on vs. off | Large cut in billed input tokens on multi-step runs; no change in accuracy | — (measurement, not hypothesis) |
| **E5** | How sensitive are results to tool output caps? | Caps at 2k / 8k / 32k characters | Accuracy flat above a threshold; cost grows linearly | Accuracy keeps rising, meaning tools return too little |

**Statistics.** Results are reported with 95 % Wilson intervals. With n ≈ 60 items, an interval is about ±10 percentage points, so differences smaller than ~15 points are **not** claimed as real. Comparisons between configurations use the **same questions** (paired), with McNemar's test for pass/fail and a paired bootstrap for continuous metrics.

---

## 4. Report format

`make eval CONFIG=eval/configs/e1.yaml` writes `eval/reports/<date>-<config>.md` containing:

| config | model | pass@1 | pass^3 | causal rubric (mean) | abstain acc. | halluc. cit. before / after | tokens / q | cost / correct | p95 latency |
|---|---|---|---|---|---|---|---|---|---|
| … | … | … | … | … | … | … | … | … | … |

Plus: a per-question-type breakdown, a list of every failed item with its transcript link, and a **cost vs. accuracy scatter plot** with one point per configuration.

**Failures are reported next to wins.** Each report ends with a section "What went wrong", with the three most common failure patterns and example transcripts.

---

## 5. Relation to real operations (later)

The same harness runs on:
1. **Replayed real logs** with labelled incidents (private, same YAML format).
2. **Shadow mode:** the assistant answers, nobody acts, answers are compared with what the crew did.
3. **Advisory mode:** operators see answers and vote 👍 / 👎. Adoption rate becomes a metric.
