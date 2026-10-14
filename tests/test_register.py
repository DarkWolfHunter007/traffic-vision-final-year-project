import pytest

from pattom.register import Register, SourceGap


def test_register_loads_and_cites(register):
    s = register.get("sp41.saturation_flow_per_m")
    assert s.value == 525
    assert s.citation == "irc_sp41_1994, p. 76"


def test_reported_values_are_marked_unchecked(register):
    assert register.get("idle_fuel_l_per_h").citation.endswith("(source not checked)")


def test_missing_value_is_a_gap(register):
    with pytest.raises(SourceGap):
        register.get("webster.delay")  # SP 41 has no delay formula (T28)


def test_missing_table_row_is_a_gap(register):
    with pytest.raises(SourceGap):
        register.item("sp41.pcu.table_III_1", "light_commercial")


@pytest.mark.parametrize(
    "entry, message",
    [
        ({"value": 1, "unit": "x", "source": "nope", "ref": "p", "status": "verified"}, "unregistered source"),
        ({"value": 1, "unit": "x", "source": "a", "ref": "p", "status": "guessed"}, "unknown status"),
        ({"value": 1, "source": "a", "ref": "p", "status": "verified"}, "lacks"),
    ],
)
def test_invalid_entries_rejected(entry, message):
    with pytest.raises(ValueError, match=message):
        Register({"sources": {"a": {}}, "values": {"k": entry}})
