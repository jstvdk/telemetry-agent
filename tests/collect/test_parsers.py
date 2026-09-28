"""Parser tests on fixtures cut from a real camera-in-a-box capture (cam-02 with injected faults:
slow-signal sensor-fault flood, SIGKILL of the chiller, missing calibration file)."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from shiftassist.collect.journal import parse_journal
from shiftassist.collect.model import LEVELS
from shiftassist.collect.monitoring import iter_samples
from shiftassist.collect.sstcam_logs import parse_lines, read_log_file, sniff

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sstcam"


# --- pipe format (per-process files) ---------------------------------------------------------


def test_pipe_header_fields() -> None:
    first = next(read_log_file(FIX / "pipe.txt"))
    assert first.ts == datetime(2026, 9, 28, 18, 25, 47, tzinfo=UTC)
    assert first.level == "INFO" and first.process == "CHILLER-CLI"
    assert first.logger == "sstcam_configuration.SETUP"
    assert first.source == "log/pipe.txt" and first.ref == "log/pipe.txt:1"


def test_pipe_message_may_contain_separator() -> None:
    e = next(x for x in read_log_file(FIX / "pipe.txt") if "TM|SIPM|FPE" in x.message)
    assert e.logger == "sstcam_configuration.SETUP"
    assert " | 70430" in e.message  # the rest of the line stays in the message


def test_pipe_multiline_record_is_one_entry() -> None:
    entries = list(read_log_file(FIX / "pipe.txt"))
    hw = [e for e in entries if e.message.startswith("Hardware error detected:")]
    assert hw, "fixture holds the flood's multi-line WARNING"
    assert hw[0].level == "WARNING" and hw[0].process == "SLOWSIGNAL-SERVER"
    assert "Temperature value not valid" in hw[0].message.splitlines()
    raw_lines = (FIX / "pipe.txt").read_text().splitlines()
    assert len(entries) < len(raw_lines), "continuation lines must not become entries"


def test_custom_levels_are_known() -> None:
    assert LEVELS["SUCCESS"] == 25 and LEVELS["VERBOSE"] == 5


def test_timezone_is_applied() -> None:
    line = "26-09-28 20:25:47 | INFO     | X | pkg | ctx | hello"
    (e,) = parse_lines([line], "pipe", "t", tz=timezone(timedelta(hours=2)))
    assert e.ts == datetime(2026, 9, 28, 18, 25, 47, tzinfo=UTC)


def test_leading_continuation_lines_are_dropped() -> None:
    lines = ["orphan continuation", "26-09-28 18:00:00 | INFO     | P | pkg | ctx | m"]
    (e,) = parse_lines(lines, "pipe", "t")
    assert e.message == "m" and e.line == 2


# --- central format (ICD) --------------------------------------------------------------------


def test_central_dialect_detected_with_millis() -> None:
    entries = list(read_log_file(FIX / "central.log"))
    assert entries[0].source.startswith("central/")
    assert entries[0].ts.microsecond % 1000 == 0 and entries[0].fields["lineno"] > 0
    hw = next(e for e in entries if e.message.startswith("Hardware error detected:"))
    assert hw.fields["func"] == "convert_spi_temp"
    assert hw.ts.microsecond != 0, "central format keeps milliseconds"
    assert len(hw.message.splitlines()) >= 5


def test_sniff() -> None:
    assert sniff("26-09-28 18:25:47 | INFO     | A | b | c | m") == "pipe"
    assert sniff("26-09-28T18:26:05.288 WARNING /p.py 215 f PROC Developer m") == "central"
    assert sniff("Sensor Hard Fault : Open or Short RTD or RSENSE") is None


# --- journal ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def journal() -> list:  # type: ignore[type-arg]
    return list(parse_journal((FIX / "journal.jsonl").open()))


def test_journal_unit_lifecycle(journal: list) -> None:  # type: ignore[type-arg]
    chiller = [e for e in journal if e.kind == "unit" and e.unit == "sstcam-chiller.service"]
    events = [e.fields["event"] for e in chiller]
    assert "exited" in events and "restart_scheduled" in events
    exited = next(e for e in chiller if e.fields["event"] == "exited")
    assert exited.fields["code"] == "killed" and exited.fields["status"] == "9/KILL"
    restart = next(e for e in chiller if e.fields["event"] == "restart_scheduled")
    assert restart.fields["n"] == "1"


def test_journal_ignores_non_camera_units(journal: list) -> None:  # type: ignore[type-arg]
    assert not any("dbus" in (e.unit or "") for e in journal)


def test_journal_traceback_reassembled(journal: list) -> None:  # type: ignore[type-arg]
    (tb,) = [e for e in journal if e.kind == "traceback"]
    assert tb.level == "ERROR", "journal says INFO; a crash traceback is an error"
    assert tb.unit == "sstcam-slowsignal.service"
    assert tb.fields["exception"] == "FileNotFoundError"
    assert tb.message.startswith("Traceback (most recent call last):")
    assert "slowsig_calibration_coefficients_per_pixel_matched.csv" in tb.fields["exception_line"]


def test_journal_mirror_log_keeps_continuations(journal: list) -> None:  # type: ignore[type-arg]
    mirrors = [e for e in journal if e.kind == "log" and e.fields.get("mirror")]
    hw = [e for e in mirrors if e.message.startswith("Hardware error detected:")]
    assert hw and len(hw[0].message.splitlines()) >= 5
    assert not [e for e in journal if e.kind == "stdout" and "Sensor" in e.message]


def test_journal_traceback_chain() -> None:
    def rec(i: int, m: str) -> str:
        return json.dumps(
            {
                "__REALTIME_TIMESTAMP": str(1_790_000_000_000_000 + i),
                "_SYSTEMD_USER_UNIT": "sstcam-x.service",
                "_PID": "7",
                "MESSAGE": m,
            }
        )

    lines = [
        "Traceback (most recent call last):",
        '  File "a.py", line 1, in f',
        "KeyError: 'a'",
        "",
        "During handling of the above exception, another exception occurred:",
        "",
        "Traceback (most recent call last):",
        '  File "b.py", line 2, in g',
        "ValueError: bad",
        "26-09-28 18:00:00 | INFO     | X | p | c | next record",
    ]
    out = list(parse_journal(rec(i, m) for i, m in enumerate(lines)))
    tb = [e for e in out if e.kind == "traceback"]
    assert len(tb) == 1 and tb[0].fields["exception"] == "ValueError"
    assert "KeyError: 'a'" in tb[0].message
    assert out[-1].kind == "log" and out[-1].message == "next record"


# --- monitoring ------------------------------------------------------------------------------


def test_monitoring_flattening() -> None:
    samples = list(iter_samples((FIX / "monitoring.jsonl").open()))
    subsystems = {s.subsystem for s in samples}
    assert {"chiller", "slowboard", "slowsignal", "eventbuilder"} <= subsystems
    chans = {(s.subsystem, s.channel) for s in samples}
    assert ("chiller", "supply_temperature") in chans
    assert ("slowboard", "fans_1.speeds.0") in chans  # list -> indexed channels
    assert ("eventbuilder", "listener.n_packets_received") in chans  # int64-as-string
    ss = [s for s in samples if s.subsystem == "slowsignal"]
    assert ss and all(s.entity.startswith("tm") for s in ss)
    assert not any(s.channel.startswith(("bias_voltage_v", "trigger_counts")) for s in ss)
    assert all(s.ts.tzinfo is not None for s in samples)
