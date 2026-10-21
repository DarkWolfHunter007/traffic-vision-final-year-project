import csv

import pytest

from pattom.count_check import compare
from pattom.graph import calibration as calib


def test_count_check(tmp_path):
    m = tmp_path / "manual.csv"
    m.write_text("interval_start_s,interval_end_s,line_name,class,count\n0,60,N,car,10\n0,60,N,bus,2\n")
    a = tmp_path / "interval_counts.csv"
    a.write_text("slot,interval_start_s,interval_end_s,line_name,line_type,approach,movement,class,count,value_type\n"
                 "s,0,60,N,arrival,north,unknown,car,9,measured\ns,60,120,N,arrival,north,unknown,car,50,measured\n")
    rows = {(r["line_name"], r["class"]): r for r in csv.DictReader(open(compare(m, a)))}
    assert rows[("N", "car")]["error_pct"] == "-10.0"
    assert rows[("N", "bus")]["automatic"] == "0"
    assert rows[("ALL", "ALL")]["manual"] == "12"


def test_signal_log_save_checks_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(calib, "SIGNAL_LOG", tmp_path / "signal_log.csv")
    (tmp_path / "signal_log.csv").write_text("time_s,signal_head,state\n0,N,green\n")
    with pytest.raises(calib.CalibrationError, match="twice"):
        calib.save_signal_log([{"time_s": 0, "signal_head": "N", "state": "green"},
                               {"time_s": 5, "signal_head": "N", "state": "green"}])
    r = calib.save_signal_log([{"time_s": 0, "signal_head": "N", "state": "green"},
                               {"time_s": 50, "signal_head": "N", "state": "amber"},
                               {"time_s": 53, "signal_head": "N", "state": "red"},
                               {"time_s": 120, "signal_head": "N", "state": "green"}])
    assert r["complete_cycles"] == {"N": 1}
    assert (tmp_path / "signal_log.csv.bak").is_file()
