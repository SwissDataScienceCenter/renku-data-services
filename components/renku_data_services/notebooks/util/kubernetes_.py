#
# Copyright 2019 - Swiss Data Science Center (SDSC)
# A partnership between École Polytechnique Fédérale de Lausanne (EPFL) and
# Eidgenössische Technische Hochschule Zürich (ETHZ).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Kubernetes helper functions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import md5
from typing import Any, Self, TypeAlias

import escapism
from kubernetes.client import V1Container


def renku_1_make_server_name(safe_username: str, namespace: str, project: str, branch: str, commit_sha: str) -> str:
    """Form a unique server name for Renku 1.0 sessions.

    This is used in naming all the k8s resources created by amalthea.
    """
    server_string_for_hashing = f"{safe_username}-{namespace}-{project}-{branch}-{commit_sha}"
    server_hash = md5(server_string_for_hashing.encode(), usedforsecurity=False).hexdigest().lower()
    prefix = _make_server_name_prefix(safe_username)
    # NOTE: A K8s object name can only contain lowercase alphanumeric characters, hyphens, or dots.
    # Must be less than 253 characters long and start and end with an alphanumeric.
    # NOTE: We use server name as a label value, so, server name must be less than 63 characters.
    # NOTE: Amalthea adds 11 characters to the server name in a label, so we have only
    # 52 characters available.
    # !NOTE: For now we limit the server name to 42 characters.
    # NOTE: This is 12 + 1 + 20 + 1 + 8 = 42 characters
    return "{prefix}-{project}-{hash}".format(
        prefix=prefix[:12],
        project=escapism.escape(project, escape_char="-")[:20].lower(),
        hash=server_hash[:8],
    )


def renku_2_make_server_name(safe_username: str, project_id: str, launcher_id: str) -> str:
    """Form a unique server name for Renku 2.0 sessions.

    This is used in naming all the k8s resources created by amalthea.
    """
    server_string_for_hashing = f"{safe_username}-{project_id}-{launcher_id}"
    server_hash = md5(server_string_for_hashing.encode(), usedforsecurity=False).hexdigest().lower()
    prefix = _make_server_name_prefix(safe_username)
    # NOTE: A K8s object name can only contain lowercase alphanumeric characters, hyphens, or dots.
    # Must be less than 253 characters long and start and end with an alphanumeric.
    # NOTE: We use server name as a label value, so, server name must be less than 63 characters.
    # NOTE: Amalthea adds 11 characters to the server name in a label, so we have only
    # 52 characters available.
    # !NOTE: For now we limit the server name to 42 characters.
    # NOTE: This is 12 + 9 + 21 = 42 characters
    return f"{prefix[:12]}-renku-2-{server_hash[:21]}"


def find_env_var(container: V1Container, env_name: str) -> tuple[int, str] | None:
    """Find the index and value of a specific environment variable by name from a Kubernetes container."""
    env_var = next(
        filter(
            lambda x: x[1].name == env_name,
            enumerate(container.env),
        ),
        None,
    )
    if not env_var:
        return None
    ind = env_var[0]
    val = env_var[1].value
    return ind, val


def _make_server_name_prefix(safe_username: str) -> str:
    safe_username_lowercase = safe_username.lower()
    prefix = ""
    if not safe_username_lowercase[0].isalpha() or not safe_username_lowercase[0].isascii():
        # NOTE: Username starts with an invalid character. This has to be modified because a
        # k8s service object cannot start with anything other than a lowercase alphabet character.
        # NOTE: We do not have worry about collisions with already existing servers from older
        # versions because the server name includes the hash of the original username, so the hash
        # would be different because the original username differs between someone whose username
        # is for example 7User vs. n7User.
        prefix = "n"

    prefix = f"{prefix}{safe_username_lowercase}"
    return prefix


JsonPatch: TypeAlias = list[dict[str, Any]]
MergePatch: TypeAlias = dict[str, Any]


class PatchKind(StrEnum):
    """Content types for different json patches."""

    json: str = "application/json-patch+json"
    merge: str = "application/merge-patch+json"


@dataclass
class Patch:
    """Representation of a JSON patch."""

    patch: JsonPatch | MergePatch
    type: PatchKind

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create a patch from a dictionary."""
        return cls(data["patch"], PatchKind(data["type"]))


def find_container(patches: list[Patch], container_name: str) -> dict[str, Any] | None:
    """Find the json patch corresponding a given container."""
    for patch_obj in patches:
        if patch_obj.type != PatchKind.json or not isinstance(patch_obj.patch, list):
            continue
        for p in patch_obj.patch:
            if (
                p.get("op") == "add"
                and p.get("path") == "/statefulset/spec/template/spec/containers/-"
                and p.get("value", {}).get("name") == container_name
            ):
                return p
    return None
