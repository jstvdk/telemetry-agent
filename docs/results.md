# Results

Measured numbers only. Every row names its data and the code version; failures are listed next to wins. How these numbers were produced: [PROVENANCE P-13 to P-15](PROVENANCE.md).

## Detector v0 (deterministic rules, tag `detector-v0`)

Profile learned from **B00** (31-min clean camera). Code frozen and tagged **before** the held-out data existed; the held-out scenarios were committed before any detector code (`ea6ac47` → `9694c53`).

| data | role | faults | expected events | recall | recall, exact module | events | precision strict / lenient | false alarms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| B00 | profile source | 0 | 0 | – | – | 0 | – | 0 (by construction) |
| B01 | dev (inspected, tuned on) | 8 | 18 | 18/18 | 17/18 | 23 | 78% / 100% | 0 |
| **B02** | **held-out** | 10 | 16 validated (19 labelled) | **15/16** (conservative) | **14/16** | 21 | 76% / 100% | **0** |
| **B00b** | **held-out, clean** | 0 | 0 | – | – | 1 | – | **1 in 46 min (1.3 /h)** |

Median detection delay on B02: gaps 1 s, restarts 6 s, tracebacks 14 s, trends 79 s. The hardest case, a 1.5 °C/h drift on one SiPM sensor (~0.15 °C over 6 min, same order as the shared ambient variation), was detected **131 s** after it started.

**What the numbers do not show, stated plainly**

- **3 of 19 B02 expected events were not ground truth.** The label said a frozen gatherer causes monitoring gaps; the data shows the gatherer buffers everything and writes it late with the original timestamps (61/61 messages per 1 Hz source during a 62 s freeze). The label validation step caught this before scoring; the 3 events are excluded, not re-labelled. Without validation: 15/19 (79 %).
- **One B02 "match" was credited by the scorer but is not real:** the slow-signal gap matched to the gatherer freeze (L08) is the gap of the calibration fault (L09) that started 6 s after it. Counted as a miss above (15/16, not the 16/16 the scorer printed). Scorer fix pending: one event, one label.
- **The false alarm on B00b** is a chiller trend at +3.87 °C/h against a threshold of 3.86 °C/h. Thresholds are "largest value in a 31-min baseline x 1.5"; a longer run eventually exceeds them. Needs a longer baseline or a tail-based threshold.
- **Localisation:** a broken RTD is found (log burst) but cannot be attributed to its module; the camera's log line does not name it (R18).
- **Small data:** 26 faults in total across dev and held-out. Enough to find design errors, not enough for tight confidence intervals.
- **Synthetic slow-signal values** (realistic structure, assumed nominal numbers) and mock chiller values; the camera software and its failure behaviour are real.
