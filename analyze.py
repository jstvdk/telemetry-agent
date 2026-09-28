"""Cost and token summary per model from usage.csv (+ accuracy if answers.csv is scored)."""
import pandas as pd

# USD per million tokens. FILL IN from the official pricing page before trusting the numbers.
PRICES = {
    "claude-haiku-4-5-20251001": {"in": None, "out": None},
    "claude-sonnet-5": {"in": None, "out": None},
}

u = pd.read_csv("usage.csv")
per_run = u.groupby(["model", "run_id"]).agg(
    calls=("step", "count"), input_tokens=("input_tokens", "sum"), output_tokens=("output_tokens", "sum")
).reset_index()

def cost(row):
    p = PRICES.get(row.model, {})
    if p.get("in") is None:
        return float("nan")
    return (row.input_tokens * p["in"] + row.output_tokens * p["out"]) / 1e6

per_run["cost_usd"] = per_run.apply(cost, axis=1)
summary = per_run.groupby("model").agg(
    runs=("run_id", "count"), avg_calls=("calls", "mean"), avg_input=("input_tokens", "mean"),
    avg_output=("output_tokens", "mean"), avg_cost_usd=("cost_usd", "mean"), total_cost_usd=("cost_usd", "sum"),
)
print(summary.round(4).to_string())

try:
    a = pd.read_csv("answers.csv", header=None,
                    names=["run_id", "model", "qid", "question", "expected", "answer", "correct"])
    scored = a.dropna(subset=["correct"])
    if len(scored):
        acc = scored.groupby("model")["correct"].agg(["mean", "count"])
        acc["std_err"] = (acc["mean"] * (1 - acc["mean"]) / acc["count"]) ** 0.5
        print("\nAccuracy (fill the 'correct' column with 1/0 first):")
        print(acc.round(3).to_string())
except FileNotFoundError:
    pass
