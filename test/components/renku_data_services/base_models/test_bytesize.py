"""Tests for the ByteSize type."""

from renku_data_services.base_models.bytesize import ByteSize


def test_max_value_for_int64_gibi() -> None:
    """Determine the max vlue in GiBi we can store as an int64 (bigint in PostgreSQL)."""

    max_int64 = 9223372036854775807  # = 2**63-1: the maximum value we can store as an int64
    max_gibi_value_int64 = max_int64 // ByteSize.GIBI
    assert max_gibi_value_int64 == 8589934591

    # This next test block shows that "8589934591 + 1" exceeds the maximum ByteSize value
    # we can store with the renku_data_services.utils.sqlalchemy.ByteSizeType adapter.
    overflow = max_gibi_value_int64 + 1
    overflow_bytes = ByteSize.from_gibi(overflow)
    assert overflow_bytes.value > max_int64
    # This means "ByteSize.from_gibi(8589934592)" would get rejected as a bigint by postgres.
