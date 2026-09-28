"""Subscribe to the mock-monitoring ZMQ stream and store every message in SQLite."""
import sqlite3
import sys
import time
from pathlib import Path

import zmq

ADDRESS = sys.argv[1] if len(sys.argv) > 1 else "tcp://localhost:5556"
DB = Path(__file__).parent / "telemetry.db"

con = sqlite3.connect(DB)
con.execute("PRAGMA journal_mode=WAL")  # lets the tools read while we write
con.execute("CREATE TABLE IF NOT EXISTS messages (ts REAL, topic TEXT, text TEXT)")

sock = zmq.Context().socket(zmq.SUB)
sock.connect(ADDRESS)
sock.setsockopt_string(zmq.SUBSCRIBE, "")  # empty prefix = subscribe to everything

print(f"Collecting from {ADDRESS} into {DB} (Ctrl+C to stop)")
n = 0
while True:
    frames = [f.decode("utf-8", errors="replace") for f in sock.recv_multipart()]
    topic, text = (frames[0], " ".join(frames[1:])) if len(frames) > 1 else ("", frames[0])
    con.execute("INSERT INTO messages VALUES (?, ?, ?)", (time.time(), topic, text))
    con.commit()
    n += 1
    if n % 100 == 0:
        print(f"{n} messages stored")
