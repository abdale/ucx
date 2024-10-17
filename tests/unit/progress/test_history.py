import datetime as dt
import re
from dataclasses import dataclass, field
from typing import ClassVar
from unittest.mock import create_autospec

import pytest
from databricks.labs.lsql.core import Row

from databricks.labs.ucx.__about__ import __version__ as ucx_version
from databricks.labs.ucx.framework.owners import Ownership
from databricks.labs.ucx.progress.history import HistoricalEncoder, HistoryLog
from databricks.labs.ucx.progress.install import Historical


@dataclass(frozen=True, kw_only=True)
class _TestRecord:
    a_field: str
    b_field: int
    failures: list[str]

    __id_fields__: ClassVar[tuple[str]] = ("a_field",)


@pytest.fixture
def ownership() -> Ownership:
    mock_ownership = create_autospec(Ownership)
    mock_ownership.owner_of.return_value = "mickey"
    return mock_ownership


def test_historical_encoder_basic(ownership) -> None:
    """Verify basic encoding of a test record into a historical record."""
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_TestRecord)

    assert ownership.owner_of(_TestRecord(a_field="fu", b_field=2, failures=["doh", "ray"])) == "mickey"

    record = encoder.to_historical(_TestRecord(a_field="fu", b_field=2, failures=["doh", "ray"]))

    expected_record = Historical(
        workspace_id=2,
        job_run_id=1,
        object_type="_TestRecord",
        object_id=["fu"],
        data={
            "a_field": "fu",
            "b_field": "2",
        },
        failures=["doh", "ray"],
        owner="mickey",
        ucx_version=ucx_version,
    )

    assert record == expected_record


def test_historical_encoder_workspace_id(ownership) -> None:
    """Verify the encoder produces records using the supplied workspace identifier."""
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=52, ownership=ownership, klass=_TestRecord)

    record = _TestRecord(a_field="whatever", b_field=2, failures=[])
    historical = encoder.to_historical(record)
    assert historical.workspace_id == 52


def test_historical_encoder_run_id(ownership) -> None:
    """Verify the encoder produces records using the supplied job-run identifier."""
    encoder = HistoricalEncoder(job_run_id=42, workspace_id=2, ownership=ownership, klass=_TestRecord)

    record = _TestRecord(a_field="whatever", b_field=2, failures=[])
    historical = encoder.to_historical(record)
    assert historical.job_run_id == 42


def test_historical_encoder_ucx_version(ownership) -> None:
    """Verify the encoder produces records containing the current UCX version."""
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_TestRecord)

    record = _TestRecord(a_field="whatever", b_field=2, failures=[])
    historical = encoder.to_historical(record)
    assert historical.ucx_version == ucx_version


def test_historical_encoder_ownership(ownership) -> None:
    """Verify the encoder produces records with the owner determined by the supplied ownership instance."""
    expected_owners = ("bob", "jane", "tarzan")
    ownership.owner_of.side_effect = expected_owners

    records = [_TestRecord(a_field="whatever", b_field=x, failures=[]) for x in range(len(expected_owners))]
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_TestRecord)

    encoded_records = [encoder.to_historical(record) for record in records]
    owners = tuple(encoded_record.owner for encoded_record in encoded_records)

    assert owners == expected_owners
    assert ownership.owner_of.call_count == 3


def test_historical_encoder_object_type(ownership) -> None:
    """Verify the encoder uses the name of the record type as the object type for records."""
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_TestRecord)

    record = _TestRecord(a_field="whatever", b_field=2, failures=[])
    historical = encoder.to_historical(record)
    assert historical.object_type == "_TestRecord"


def test_historical_encoder_object_id(ownership) -> None:
    """Verify the encoder uses the configured object-id fields from the record type in the encoded records."""
    encoder1 = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_TestRecord)

    historical1 = encoder1.to_historical(_TestRecord(a_field="used_for_key", b_field=2, failures=[]))
    assert historical1.object_id == ["used_for_key"]

    @dataclass
    class _CompoundKey:
        a_field: str = "field-a"
        b_field: str = "field-b"
        c_field: str = "field-c"

        __id_fields__: ClassVar = ("a_field", "c_field", "b_field")

    encoder2 = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_CompoundKey)
    historical2 = encoder2.to_historical(_CompoundKey())

    # Note: order matters
    assert historical2.object_id == ["field-a", "field-c", "field-b"]


def test_historical_encoder_object_id_verification(ownership) -> None:
    """Check the __id_fields__ class property is verified during init: it must be present and refer only to strings."""

    @dataclass
    class _NoIdFields:
        pass

    @dataclass
    class _WrongTypeIdFields:
        ok: str
        not_ok: int

        __id_fields__: ClassVar = ["ok", "not_ok"]

    with pytest.raises(AttributeError) as excinfo:
        HistoricalEncoder(job_run_id=1, workspace_id=1, ownership=ownership, klass=_NoIdFields)

    assert excinfo.value.obj == _NoIdFields
    assert excinfo.value.name == "__id_fields__"

    with pytest.raises(TypeError, match="Historical record class id field is not a string: not_ok"):
        HistoricalEncoder(job_run_id=1, workspace_id=1, ownership=ownership, klass=_WrongTypeIdFields)


def test_historical_encoder_object_data(ownership) -> None:
    """Verify the encoder includes all dataclass fields in the object data."""
    encoder1 = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_TestRecord)

    historical1 = encoder1.to_historical(_TestRecord(a_field="used_for_key", b_field=2, failures=[]))
    assert set(historical1.data.keys()) == {"a_field", "b_field"}

    @dataclass
    class _AnotherClass:
        field_1: str = "foo"
        field_2: str = "bar"
        field_3: str = "baz"
        field_4: str = "daz"

        __id_fields__: ClassVar = ("field_1",)

    encoder2 = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_AnotherClass)
    historical2 = encoder2.to_historical(_AnotherClass())
    assert set(historical2.data.keys()) == {"field_1", "field_2", "field_3", "field_4"}


def test_historical_encoder_object_data_values_strings_as_is(ownership) -> None:
    """Verify that string fields are encoded as-is in the object_data"""

    @dataclass
    class _AClass:
        a_field: str = "value"
        existing_json_field: str = "[1, 2, 3]"
        optional_string_field: str | None = "value"

        __id_fields__: ClassVar = ("a_field",)

    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_AClass)
    historical = encoder.to_historical(_AClass())
    assert historical.data == {"a_field": "value", "existing_json_field": "[1, 2, 3]", "optional_string_field": "value"}


def test_historical_encoder_object_data_missing_optional_values(ownership) -> None:
    """Verify the encoding of missing (optional) field values."""

    @dataclass(frozen=True)
    class _InnerClass:
        optional_field: str | None = None

    @dataclass
    class _AClass:
        a_field: str = "value"
        optional_field: str | None = None
        nested: _InnerClass = _InnerClass()

        __id_fields__: ClassVar = ("a_field",)

    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_AClass)
    historical = encoder.to_historical(_AClass())
    assert "optional_field" not in historical.data, "First-level optional fields should be elided if None"
    assert historical.data["nested"] == '{"optional_field":null}', "Nested optional fields should be encoded as nulls"


def test_historical_encoder_object_data_values_non_strings_as_json(ownership) -> None:
    """Verify that non-string fields are encoded as JSON in the object_data"""

    @dataclass(frozen=True)
    class _InnerClass:
        counter: int
        boolean: bool = True
        a_field: str = "bar"
        optional: str | None = None

    # TODO: Expand to cover all lsql-supported types.
    @dataclass
    class _AClass:
        str_field: str = "foo"
        int_field: int = 23
        bool_field: bool = True
        ts_field: dt.datetime = field(
            default_factory=lambda: dt.datetime(
                year=2024, month=10, day=15, hour=12, minute=44, second=16, tzinfo=dt.timezone.utc
            )
        )
        array_field: list[str] = field(default_factory=lambda: ["foo", "bar", "baz"])
        nested_dataclass: list[_InnerClass] = field(default_factory=lambda: [_InnerClass(x) for x in range(2)])

        __id_fields__: ClassVar = ("str_field",)

    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_AClass)
    historical = encoder.to_historical(_AClass())
    assert historical.data == {
        "str_field": "foo",
        "int_field": "23",
        "bool_field": "true",
        "ts_field": "2024-10-15T12:44:16Z",
        "array_field": '["foo","bar","baz"]',
        "nested_dataclass": '[{"counter":0,"boolean":true,"a_field":"bar","optional":null},{"counter":1,"boolean":true,"a_field":"bar","optional":null}]',
    }


@dataclass(frozen=True, kw_only=True)
class _InnerClassWithTimestamp:
    b_field: dt.datetime


@dataclass(frozen=True, kw_only=True)
class _OuterclassWithTimestamps:
    object_id: str = "not used"
    a_field: dt.datetime | None = None
    inner: _InnerClassWithTimestamp | None = None

    __id_fields__: ClassVar = ("object_id",)


@pytest.mark.parametrize(
    "field_name,record",
    (
        ("a_field", _OuterclassWithTimestamps(a_field=dt.datetime.now())),
        ("inner", _OuterclassWithTimestamps(inner=_InnerClassWithTimestamp(b_field=dt.datetime.now()))),
    ),
)
def test_historical_encoder_naive_timestamps_banned(ownership, field_name, record: _OuterclassWithTimestamps) -> None:
    """Verify that encoding detects and disallows naive timestamps."""
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_OuterclassWithTimestamps)

    expected_msg = f"Timestamp without timezone not supported in or within field {field_name}"
    with pytest.raises(ValueError, match=f"^{re.escape(expected_msg)}"):
        _ = encoder.to_historical(record)


@dataclass(frozen=True, kw_only=True)
class _InnerClassWithUnserializable:
    b_field: object


@dataclass(frozen=True, kw_only=True)
class _OuterclassWithUnserializable:
    object_id: str = "not used"
    a_field: object | None = None
    inner: _InnerClassWithUnserializable | None = None

    __id_fields__: ClassVar = ("object_id",)


@pytest.mark.parametrize(
    "field_name,record",
    (
        ("a_field", _OuterclassWithUnserializable(a_field=object())),
        ("inner", _OuterclassWithUnserializable(inner=_InnerClassWithUnserializable(b_field=object()))),
    ),
)
def test_historical_encoder_unserializable_values(ownership, field_name, record: _OuterclassWithUnserializable) -> None:
    """Verify that encoding catches and handles unserializable values."""
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_OuterclassWithUnserializable)

    expected_msg = f"^Cannot encode .* value in or within field {re.escape(field_name)}: "
    with pytest.raises(TypeError, match=expected_msg):
        _ = encoder.to_historical(record)


@pytest.mark.parametrize("failures", (["failures-1", "failures-2"], []))
def test_historical_encoder_failures(ownership, failures: list[str]) -> None:
    """Verify an encoder places failures on the top-level field instead of within the object data."""
    encoder = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_TestRecord)

    historical = encoder.to_historical(_TestRecord(a_field="foo", b_field=10, failures=list(failures)))

    assert historical.failures == failures
    assert "failures" not in historical.data


def test_historical_encoder_failures_verification(ownership) -> None:
    """Verify that encoders checks the failures field type during initialization."""

    @dataclass
    class _BrokenFailures:
        a_field: str = "a_field"
        failures: list[int] = field(default_factory=list)

        __id_fields__: ClassVar = ("a_field",)

    with pytest.raises(TypeError, match=re.escape("Historical record class has invalid failures type: list[int]")):
        _ = HistoricalEncoder(job_run_id=1, workspace_id=2, ownership=ownership, klass=_BrokenFailures)


def test_history_log_appends_historical_records(ws, mock_backend, ownership) -> None:
    """Verify that we can journal a snapshot of records to the historical log."""
    ownership.owner_of.side_effect = lambda o: f"owner-{o.a_field}"

    records = (
        _TestRecord(a_field="first_record", b_field=1, failures=[]),
        _TestRecord(a_field="second_record", b_field=2, failures=["a_failure"]),
        _TestRecord(a_field="third_record", b_field=3, failures=["another_failure", "yet_another_failure"]),
    )
    expected_historical_entries = (
        Row(
            workspace_id=2,
            job_run_id=1,
            object_type="_TestRecord",
            object_id=["first_record"],
            data={"a_field": "first_record", "b_field": "1"},
            failures=[],
            owner="owner-first_record",
            ucx_version=ucx_version,
        ),
        Row(
            workspace_id=2,
            job_run_id=1,
            object_type="_TestRecord",
            object_id=["second_record"],
            data={"a_field": "second_record", "b_field": "2"},
            failures=["a_failure"],
            owner="owner-second_record",
            ucx_version=ucx_version,
        ),
        Row(
            workspace_id=2,
            job_run_id=1,
            object_type="_TestRecord",
            object_id=["third_record"],
            data={"a_field": "third_record", "b_field": "3"},
            failures=["another_failure", "yet_another_failure"],
            owner="owner-third_record",
            ucx_version=ucx_version,
        ),
    )

    history_log = HistoryLog(
        ws,
        mock_backend,
        ownership,
        _TestRecord,
        run_id=1,
        workspace_id=2,
        catalog="the_catalog",
        schema="the_schema",
        table="the_table",
    )
    history_log.append_inventory_snapshot(records)

    rows_appended = mock_backend.rows_written_for("`the_catalog`.`the_schema`.`the_table`", mode="append")
    assert rows_appended == list(expected_historical_entries)


def test_history_log_default_location(ws, mock_backend, ownership) -> None:
    """Verify that the history log defaults to the ucx.history in the configured catalog."""

    record = _TestRecord(a_field="foo", b_field=1, failures=[])
    history_log = HistoryLog(ws, mock_backend, ownership, _TestRecord, run_id=1, workspace_id=2, catalog="the_catalog")
    history_log.append_inventory_snapshot([record])

    assert history_log.full_name == "the_catalog.ucx.history"
    assert mock_backend.has_rows_written_for("`the_catalog`.`ucx`.`history`")