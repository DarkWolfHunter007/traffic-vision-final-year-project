from backend.media import TimestampAudit


def test_timestamp_audit_marks_variable_cadence() -> None:
    audit = TimestampAudit()
    for timestamp in (0.0, 0.04, 0.08, 0.13):
        audit.observe(timestamp)
    assert audit.variable_frame_rate is True
    assert audit.as_dict()["timestamp_quality"] == "continuous"


def test_timestamp_audit_marks_missing_or_non_monotonic_pts() -> None:
    audit = TimestampAudit()
    for timestamp in (0.0, 0.04, 0.04, None):
        audit.observe(timestamp)
    assert audit.as_dict()["timestamp_quality"] == "discontinuous"
