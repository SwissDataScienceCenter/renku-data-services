"""Tests for the logs collector."""

import pytest
from ulid import ULID

from renku_data_services.persisted_logs import loki_api, models
from renku_data_services.persisted_logs.collector import LokiLogReader


@pytest.mark.asyncio
async def test_process_session_logs(session_logs_response: loki_api.LokiQueryRangeResponse) -> None:
    log_stream = LokiLogReader._process_session_logs(session_logs_response)
    unsaved_log_lines: list[models.UnsavedSessionLogLine] = []
    async for item in log_stream:
        unsaved_log_lines.append(item)

    assert unsaved_log_lines is not None
    assert len(unsaved_log_lines) == 22

    expected_log_line_1 = models.UnsavedSessionLogLine(
        id="1785482085020548955::git-clone::j-flora-thie-a8944af936b5-7mjnh",
        user_id="d62fb7cb-7893-4149-8917-19e8d882cdd0",
        run_id=ULID.from_str("01KYVGCNJ3CJ1EQKF343JEEV6T"),
        session_uid="6c5596f3-b27d-4b71-8d37-e672eb66b866",
        launcher_id=ULID.from_str("01KXNAFYMJ42QCEGG6739T28RS"),
        submission_id="run-8ej4lg",
        container="git-clone",
        timestamp=1785482085020548955,
        log_line="2026/07/31 07:14:45 Setting up repository.\n",
    )
    assert expected_log_line_1 in unsaved_log_lines

    expected_log_line_2 = models.UnsavedSessionLogLine(
        id="1785482091170410038::amalthea-session::j-flora-thie-a8944af936b5-7mjnh",
        user_id="d62fb7cb-7893-4149-8917-19e8d882cdd0",
        run_id=ULID.from_str("01KYVGCNJ3CJ1EQKF343JEEV6T"),
        session_uid="6c5596f3-b27d-4b71-8d37-e672eb66b866",
        launcher_id=ULID.from_str("01KXNAFYMJ42QCEGG6739T28RS"),
        submission_id="run-8ej4lg",
        container="amalthea-session",
        timestamp=1785482091170410038,
        log_line="7/10\n",
    )
    assert expected_log_line_2 in unsaved_log_lines


@pytest.mark.asyncio
async def test_process_build_logs(build_logs_response: loki_api.LokiQueryRangeResponse) -> None:
    log_stream = LokiLogReader._process_image_build_logs(build_logs_response)
    unsaved_log_lines: list[models.UnsavedBuildLogLine] = []
    async for item in log_stream:
        unsaved_log_lines.append(item)

    assert unsaved_log_lines is not None
    assert len(unsaved_log_lines) == 3

    expected_log_line = models.UnsavedBuildLogLine(
        id="1785482342006624181::step-build-and-push::renku-01kyvgffxtxv4qk0dyjkx0zsa5-ttr4v-pod",
        build_id=ULID.from_str("01KYVGFFXTXV4QK0DYJKX0ZSA5"),
        container="step-build-and-push",
        timestamp=1785482342006624181,
        log_line="Saving harbor.dev.renku.ch/renku-build/renku-build:renku-01kyvgffxtxv4qk0dyjkx0zsa5...\n",
    )
    assert expected_log_line in unsaved_log_lines
