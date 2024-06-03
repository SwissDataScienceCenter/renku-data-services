import logging
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Any

import pytest
from deepmerge import Merger
from deepmerge.strategy.dict import DictStrategies
from sanic_testing.testing import SanicASGITestClient
from yaml import safe_dump, safe_load


@pytest.mark.asyncio
async def test_smoke(sanic_client: SanicASGITestClient) -> None:
    _, res = await sanic_client.get("/api/data/version")
    assert res.status_code == 200


def test_apispec_conflicts() -> None:
    """Check if conflicts exist in unexpected fields in the apispec schemas when merging."""

    @dataclass
    class ApispecMergeError(Exception):
        path: str
        diff: str

    def merge_dict_strategy(config: Merger, path: list, base: dict, nxt: dict) -> dict:
        """A modified merge strategy that will error out on conflicts in specific fields."""
        conflict_not_allowed = [
            # Any indicates that the field must be present but its value is irrelevant
            ["components", Any, Any],
            ["paths", Any],
        ]
        for disallowed_path in conflict_not_allowed:
            if len(path) < len(disallowed_path):
                continue
            path_match = all(map(lambda x: x[1] == Any or x[1] == path[x[0]], enumerate(disallowed_path)))
            if not path_match:
                continue
            base_yml = safe_dump(base)
            nxt_yml = safe_dump(nxt)
            if base_yml == nxt_yml:
                continue
            path_join = ".".join(path)
            diff = "\n".join(unified_diff(base_yml.splitlines(), nxt_yml.splitlines(), path_join, path_join))
            raise ApispecMergeError(path_join, diff)

        return DictStrategies.strategy_merge(config, path, base, nxt)

    merger = Merger(
        type_strategies=[(list, "append_unique"), (dict, merge_dict_strategy), (set, "union")],
        fallback_strategies=["use_existing"],
        type_conflict_strategies=["use_existing"],
    )
    apispec_files = list(Path(".").glob("**/api.spec.yaml"))
    if len(apispec_files) < 2:
        return
    with open(apispec_files[0]) as f:
        base_dict = safe_load(f)
    for input_file in apispec_files[1:]:
        logging.info(f"Testing merge on {input_file}")
        with open(input_file) as f:
            to_merge = safe_load(f)
        try:
            merger.merge(base_dict, to_merge)
        except ApispecMergeError as err:
            assert False, f"There was an unexpected conflict when merging {input_file} at field {err.path}\n{err.diff}"
