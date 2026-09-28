"""Run every question in questions.jsonl with each model; save answers for scoring."""
import csv
import json
import sys

from agent import run

models = sys.argv[1:] or ["claude-haiku-4-5-20251001"]
questions = [json.loads(line) for line in open("questions.jsonl") if line.strip()]

with open("answers.csv", "a", newline="") as f:
    w = csv.writer(f)
    for model in models:
        for q in questions:
            run_id = f"{q['id']}|{model}"
            print(f"\n=== {run_id}: {q['question']}")
            answer = run(q["question"], model, run_id=run_id)
            print(answer)
            w.writerow([run_id, model, q["id"], q["question"], q["expected"], answer, ""])
            f.flush()
