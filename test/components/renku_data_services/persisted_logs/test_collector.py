"""Tests for the logs collector."""

import pytest
from ulid import ULID

from renku_data_services.persisted_logs import loki_api, models
from renku_data_services.persisted_logs.collector import LokiLogReader


@pytest.fixture
def session_logs_response() -> loki_api.LokiQueryRangeResponse:
    json_content = """
{
  "status": "success",
  "data": {
    "resultType": "streams",
    "result": [
      {
        "stream": {
          "app": "AmaltheaSession",
          "container": "git-clone",
          "container_runtime": "containerd",
          "detected_level": "unknown",
          "instance": "renku-ci-ds-1383/j-flora-thie-a8944af936b5-7mjnh:git-clone",
          "job": "renku-ci-ds-1383/git-clone",
          "namespace": "renku-ci-ds-1383",
          "pod": "j-flora-thie-a8944af936b5-7mjnh",
          "renku_io_launcher_id": "01KXNAFYMJ42QCEGG6739T28RS",
          "renku_io_pod_uid": "c7341da8-5333-47fc-87f4-b364b0ea9c1c",
          "renku_io_project_id": "01KXJZF4YH8G2CP9TDNJJPAWNF",
          "renku_io_run_id": "01KYVGCNJ3CJ1EQKF343JEEV6T",
          "renku_io_safe_username": "d62fb7cb-7893-4149-8917-19e8d882cdd0",
          "renku_io_session_type": "non_interactive",
          "renku_io_session_uid": "6c5596f3-b27d-4b71-8d37-e672eb66b866",
          "renku_io_submission_id": "run-8ej4lg",
          "service_name": "AmaltheaSession"
        },
        "values": [
          [
            "1785482086378524994",
            "2026/07/31 07:14:46 Setting up git proxy to http://localhost:65480\\n"
          ],
          [
            "1785482086364418022",
            "2026/07/31 07:14:46 Dealing with submodules\\n"
          ],
          [
            "1785482086339950490",
            "2026/07/31 07:14:46 Checking out branch main\\n"
          ],
          [
            "1785482086339935443",
            "2026/07/31 07:14:46 Default branch is main\\n"
          ],
          [
            "1785482085028615483",
            "2026/07/31 07:14:45 Cloning repository /home/renku/work/renku-envs from https://gitlab.com/leafty/renku-envs.git\\n"
          ],
          [
            "1785482085026311874",
            "2026/07/31 07:14:45 Setting name Flora Thiebaut in git config\\n"
          ],
          [
            "1785482085025300000",
            "2026/07/31 07:14:45 Setting email flora.thiebaut@sdsc.ethz.ch in git config\\n"
          ],
          [
            "1785482085020557046",
            "2026/07/31 07:14:45 Initializing repo\\n"
          ],
          [
            "1785482085020548955",
            "2026/07/31 07:14:45 Setting up repository.\\n"
          ],
          [
            "1785482085019553389",
            "2026/07/31 07:14:45 Processing https://gitlab.com/leafty/renku-envs.git\\n"
          ],
          [
            "1785482085018064534",
            "2026/07/31 07:14:45 Creating clone path\\n"
          ],
          [
            "1785482085018035543",
            "2026/07/31 07:14:45 Checking if clone path: /home/renku/work/renku-envs exists\\n"
          ]
        ]
      },
      {
        "stream": {
          "app": "AmaltheaSession",
          "container": "amalthea-session",
          "container_runtime": "containerd",
          "detected_level": "unknown",
          "instance": "renku-ci-ds-1383/j-flora-thie-a8944af936b5-7mjnh:amalthea-session",
          "job": "renku-ci-ds-1383/amalthea-session",
          "namespace": "renku-ci-ds-1383",
          "pod": "j-flora-thie-a8944af936b5-7mjnh",
          "renku_io_launcher_id": "01KXNAFYMJ42QCEGG6739T28RS",
          "renku_io_pod_uid": "c7341da8-5333-47fc-87f4-b364b0ea9c1c",
          "renku_io_project_id": "01KXJZF4YH8G2CP9TDNJJPAWNF",
          "renku_io_run_id": "01KYVGCNJ3CJ1EQKF343JEEV6T",
          "renku_io_safe_username": "d62fb7cb-7893-4149-8917-19e8d882cdd0",
          "renku_io_session_type": "non_interactive",
          "renku_io_session_uid": "6c5596f3-b27d-4b71-8d37-e672eb66b866",
          "renku_io_submission_id": "run-8ej4lg",
          "service_name": "AmaltheaSession"
        },
        "values": [
          [
            "1785482091170416212",
            "10/10\\n"
          ],
          [
            "1785482091170414253",
            "9/10\\n"
          ],
          [
            "1785482091170412277",
            "8/10\\n"
          ],
          [
            "1785482091170410038",
            "7/10\\n"
          ],
          [
            "1785482091170408130",
            "6/10\\n"
          ],
          [
            "1785482091170406092",
            "5/10\\n"
          ],
          [
            "1785482091170404020",
            "4/10\\n"
          ],
          [
            "1785482091170401840",
            "3/10\\n"
          ],
          [
            "1785482091170397828",
            "2/10\\n"
          ],
          [
            "1785482091170339759",
            "1/10\\n"
          ]
        ]
      }
    ]
  }
}
"""
    return loki_api.LokiQueryRangeResponse.model_validate_json(json_content)


@pytest.fixture
def build_logs_response() -> loki_api.LokiQueryRangeResponse:
    json_content = """
{
  "status": "success",
  "data": {
    "resultType": "streams",
    "result": [
      {
        "stream": {
          "app": "ShipwrightBuildRun",
          "container": "step-build-and-push",
          "container_runtime": "containerd",
          "detected_level": "unknown",
          "instance": "renku-ci-ds-1383/renku-01kyvgffxtxv4qk0dyjkx0zsa5-ttr4v-pod:step-build-and-push",
          "job": "renku-ci-ds-1383/step-build-and-push",
          "namespace": "renku-ci-ds-1383",
          "pod": "renku-01kyvgffxtxv4qk0dyjkx0zsa5-ttr4v-pod",
          "renku_io_buildrun_name": "renku-01kyvgffxtxv4qk0dyjkx0zsa5",
          "renku_io_pod_uid": "a533d0d6-c485-4671-b3d6-643ad34bd0b6",
          "service_name": "ShipwrightBuildRun"
        },
        "values": [
          [
            "1785482346922298906",
            "      harbor.dev.renku.ch/renku-build/renku-build:renku-01kyvgffxtxv4qk0dyjkx0zsa5\\n"
          ],
          [
            "1785482346922274287",
            "*** Images (sha256:77281bcd4ffcc16bd9942dd280d1a9ef78c64fd97274cd1ec4b0d4a0c4084fef):\\n"
          ],
          [
            "1785482342006624181",
            "Saving harbor.dev.renku.ch/renku-build/renku-build:renku-01kyvgffxtxv4qk0dyjkx0zsa5...\\n"
          ]
        ]
      }
    ]
  }
}
"""
    return loki_api.LokiQueryRangeResponse.model_validate_json(json_content)


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
