import pytest

from pattom import signals


def _log(tmp_path, text):
    p = tmp_path / "log.csv"
    p.write_text("time_s,signal_head,state\n" + text)
    return p


def test_cycles_and_summary(tmp_path):
    p = _log(tmp_path, "0,N,green\n50,N,amber\n53,N,red\n120,N,green\n170,N,amber\n173,N,red\n240,N,green\n")
    log = signals.load_log(p)
    cs = signals.cycles(log["N"], "N")
    assert [(c.start_s, c.length_s, c.green_s, c.amber_s, c.red_s) for c in cs] == [
        (0, 120, 50, 3, 67), (120, 120, 50, 3, 67)]
    s = signals.summary(log)["N"]
    assert s["mean_cycle_s"] == 120 and s["value_type"] == "measured"
    assert signals.state_at(log["N"], 51) == "amber"


def test_bad_logs_rejected(tmp_path):
    with pytest.raises(ValueError, match="green, amber or red"):
        signals.load_log(_log(tmp_path, "0,N,yellow\n"))
    with pytest.raises(ValueError, match="twice in a row"):
        signals.load_log(_log(tmp_path, "0,N,green\n10,N,green\n"))
