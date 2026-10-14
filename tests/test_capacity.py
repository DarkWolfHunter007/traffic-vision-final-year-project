import pytest

from pattom import capacity
from pattom.register import SourceGap
from pattom.values import ValueType


def test_saturation_flow_formula(register):
    s = capacity.saturation_flow(7.0, register)
    assert s.value == pytest.approx(3675.0)
    assert s.value_type is ValueType.DERIVED


def test_saturation_flow_narrow_table(register):
    assert capacity.saturation_flow(4.0, register).value == 1950


def test_untabulated_narrow_width_is_a_gap(register):
    with pytest.raises(SourceGap):
        capacity.saturation_flow(4.2, register)


def test_width_above_range_is_a_gap(register):
    with pytest.raises(SourceGap):
        capacity.saturation_flow(20.0, register)


def test_gradient(register):
    assert capacity.saturation_flow(10.0, register, gradient_pct=2).value == pytest.approx(5250 * 0.94)
    assert capacity.saturation_flow(10.0, register, gradient_pct=-1).value == pytest.approx(5250 * 1.03)


def test_capacity_and_vc(register):
    s = capacity.saturation_flow(7.0, register)
    cap = capacity.capacity(40, 120, s)
    assert cap.value == pytest.approx(1225.0)
    flow = capacity.pcu_flow({"motorcycle_scooter": 200, "passenger_car": 100}, 900, "table_3_1", register)
    assert flow.value == pytest.approx(800.0)
    assert capacity.vc_ratio(flow, cap).value == pytest.approx(800 / 1225)


def test_pcu_tables_differ_for_tractor_trailer(register):
    a = capacity.pcu_flow({"tractor_trailer": 1}, 3600, "table_3_1", register)
    b = capacity.pcu_flow({"tractor_trailer": 1}, 3600, "table_III_1", register)
    assert (a.value, b.value) == (4.5, 3.0)


def test_cycle_and_split():
    co = capacity.fixed_time_cycle(8.0, [0.3, 0.2])
    assert co.value == pytest.approx((1.5 * 8 + 5) / 0.5)
    greens = capacity.green_split(60.0, [0.3, 0.2])
    assert [g.value for g in greens] == pytest.approx([36.0, 24.0])


def test_oversaturated_cycle_rejected():
    with pytest.raises(ValueError, match="oversaturated"):
        capacity.fixed_time_cycle(8.0, [0.6, 0.5])
