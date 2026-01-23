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

import re
from enum import StrEnum
from hashlib import md5
from typing import Any, TypeAlias

from box.box import Box

from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser, Slug


def renku_2_make_server_name(
    user: AuthenticatedAPIUser | AnonymousAPIUser, project_id: str, launcher_id: str, cluster_id: str
) -> str:
    """Form a unique server name for Renku 2.0 sessions.

    This is used in naming all the k8s resources created by amalthea.
    """
    safe_username = Slug.from_user(user.email, user.first_name, user.last_name, user.id).value
    safe_username = safe_username.lower()
    safe_username = re.sub(r"[^a-z0-9-]", "-", safe_username)
    prefix = _make_server_name_prefix(safe_username)
    server_string_for_hashing = f"{user.id}-{project_id}-{launcher_id}-{cluster_id}"
    server_hash = md5(server_string_for_hashing.encode(), usedforsecurity=False).hexdigest().lower()
    # NOTE: A K8s object name can only contain lowercase alphanumeric characters, hyphens, or dots.
    # Must be no more than 63 characters because the name is used to create a k8s Service and Services
    # have more restrictions for their names because their names have to make a valid hostname.
    # NOTE: We use server name as a label value, so, server name must be less than 63 characters.
    # !NOTE: For now we limit the server name to a max of 25 characters.
    # NOTE: This is 12 + 1 + 12 = 25 characters
    return f"{prefix[:12]}-{server_hash[:12]}"


def find_env_var(env_vars: list[Box], env_name: str) -> tuple[int, Box] | None:
    """Find the index and value of a specific environment variable by name from a Kubernetes container."""
    filtered = (env_var for env_var in enumerate(env_vars) if env_var[1].name == env_name)
    return next(filtered, None)


def _make_server_name_prefix(safe_username: str) -> str:
    prefix = ""
    if not safe_username[0].isalpha() or not safe_username[0].isascii():
        # NOTE: Username starts with an invalid character. This has to be modified because a
        # k8s service object cannot start with anything other than a lowercase alphabet character.
        # NOTE: We do not have worry about collisions with already existing servers from older
        # versions because the server name includes the hash of the original username, so the hash
        # would be different because the original username differs between someone whose username
        # is for example 7User vs. n7User.
        prefix = "n"

    prefix = f"{prefix}{safe_username}"
    return prefix


JsonPatch: TypeAlias = list[dict[str, Any]]
MergePatch: TypeAlias = dict[str, Any]


class PatchKind(StrEnum):
    """Content types for different json patches."""

    json = "application/json-patch+json"
    merge = "application/merge-patch+json"
