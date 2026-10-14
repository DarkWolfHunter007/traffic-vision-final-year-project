import csv

import pytest

from pattom.phases import PhaseLogError, cycles, read_phase_log, run_phases

HEADER = "slot,time_s,signal_head,state,phase_group\n"


def write(tmp_path, body):
    p = tmp_path / "phase_log.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return p


def test_complete_cycles_only(tmp_path):
    # Synthetic times for the test, not observed values.
    log = write(tmp_path, "t,5,N,red,NS\nt,10,N,green,NS\nt,40,N,amber,NS\nt,43,N,red,NS\n"
                          "t,70,N,green,NS\nt,95,N,amber,NS\nt,98,N,red,NS\n")
    [c] = cycles(read_phase_log(log, "t"))
    assert (c["green_s"], c["amber_s"], c["red_s"], c["cycle_s"]) == (30, 3, 27, 60)
    assert c["regular"] and c["value_type"] == "measured"


def test_irregular_sequence_is_flagged(tmp_path):
    log = write(tmp_path, "t,0,N,green,NS\nt,30,N,red,NS\nt,60,N,green,NS\n")
    [c] = cycles(read_phase_log(log, "t"))
    assert c["sequence"] == "green-red" and not c["regular"]


@pytest.mark.parametrize("body, match", [
    ("t,0,N,blue,NS\n", "not one of"),
    ("x,0,N,green,NS\n", "expected 't'"),
    ("t,10,N,green,NS\nt,5,N,red,NS\n", "must increase"),
    ("t,0,N,green,NS\nt,5,N,green,NS\n", "repeats state"),
    ("t,0,N,green,NS\nt,5,N,red,EW\n", "several phase groups"),
])
def test_bad_logs_are_refused(tmp_path, body, match):
    with pytest.raises(PhaseLogError, match=match):
        read_phase_log(write(tmp_path, body), "t")


def test_run_writes_files(tmp_path):
    log = write(tmp_path, "t,0,N,green,NS\nt,30,N,amber,NS\nt,33,N,red,NS\nt,60,N,green,NS\n")
    phases, cyc = run_phases(log, "t", tmp_path / "out")
    assert len(list(csv.DictReader(open(cyc)))) == 1
    assert (tmp_path / "out" / "signal_phases.run.json").exists() and phases.exists()
