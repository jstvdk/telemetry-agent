# baseline/ — v0 learning spike

The two-evening spike, moved here unchanged from the repo root (tag `v0-spike` shows it in its original place). It is kept as the **baseline configuration for experiment E1**: raw-text tools over log lines vs. the v1 structured design, same model.

Known defects are listed in [docs/06-v0-spike-review.md](../docs/06-v0-spike-review.md). Do not fix them here: the baseline has to stay as it was to be a fair comparison.

```bash
uv sync --extra baseline
cd baseline
uv run python collector.py tcp://localhost:5556     # e.g. fed by: make publish SCENARIO=S03
uv run python agent.py "Were there any errors in the last 30 minutes?"
```

The v1 simulator publishes on the same ZMQ interface (topic frame + payload frame), so the baseline can ingest simulated scenarios.
