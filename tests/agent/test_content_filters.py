import pytest

from ninjaone_agent.content_filters import (
    filter_result_payload,
    normalize_operator,
    record_matches,
)


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("begins with", "starts_with"),
        ("prefix", "starts_with"),
        ("includes", "contains"),
        ("has", "contains"),
        ("exactly", "equals"),
        ("suffix", "ends_with"),
        ("does not contain", "not_contains"),
    ],
)
def test_natural_language_operator_aliases(wording, expected):
    assert normalize_operator(wording) == expected


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("starts_with", "2qn", True),
        ("begins with", "2qn", True),
        ("contains", "LAPTOP", True),
        ("ends_with", "001", True),
        ("equals", "2QN-LAPTOP-001", True),
        ("not_contains", "SERVER", True),
        ("not_equals", "OTHER", True),
    ],
)
def test_case_insensitive_content_matching(operator, value, expected):
    record = {"systemName": "2QN-Laptop-001"}
    assert record_matches(
        record, [{"field": "system_name", "operator": operator, "value": value}]
    ) is expected


def test_filter_result_payload_filters_records_and_reports_counts():
    payload = {
        "total": 4,
        "data": [
            {"id": 1, "systemName": "2QN-PC"},
            {"id": 2, "systemName": "ABC-PC"},
            {"id": 3, "systemName": "2QN-LAPTOP"},
            {"id": 4, "systemName": "TEST-SERVER"},
        ],
    }

    filtered, summary = filter_result_payload(
        payload,
        [{"field": "systemName", "operator": "prefix", "value": "2qn"}],
    )

    assert [item["systemName"] for item in filtered["data"]] == [
        "2QN-PC", "2QN-LAPTOP"
    ]
    assert filtered["total"] == 4
    assert summary == {"examined": 4, "matched": 2}
    # Input is not mutated.
    assert len(payload["data"]) == 4


def test_filter_supports_nested_fields_and_numeric_comparisons():
    record = {"device": {"osName": "Windows 11"}, "lastContact": 12}
    assert record_matches(record, [
        {"field": "device.os_name", "operator": "contains", "value": "windows"},
        {"field": "lastContact", "operator": "greater_than_or_equal", "value": 10},
    ])


def test_filter_rejects_unknown_operator():
    with pytest.raises(ValueError, match="Unsupported filter operator"):
        normalize_operator("sounds_like")
