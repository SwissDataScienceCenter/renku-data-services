# -*- coding: utf-8 -*-
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

from hashlib import md5

import escapism
from kubernetes import client


def filter_resources_by_annotations(
    resources,
    annotations,
):
    """Fetch all the user server pods that matches the provided annotations.
    If an annotation that is not present on the pod is provided the match fails."""

    def filter_resource(resource):
        res = []
        for annotation_name in annotations.keys():
            res.append(
                resource["metadata"]["annotations"].get(annotation_name)
                == annotations[annotation_name]
            )
        if len(res) == 0:
            return True
        else:
            return all(res)

    return list(filter(filter_resource, resources))


def secret_exists(name, k8s_client, k8s_namespace):
    """Check if the secret exists."""

    try:
        k8s_client.read_namespaced_secret(name, k8s_namespace)
        return True
    except client.rest.ApiException:
        pass
    return False


def make_server_name(
    safe_username: str, namespace: str, project: str, branch: str, commit_sha: str
) -> str:
    """Form a unique server name.

    This is used in naming all of the k8s resources created by amalthea.
    """
    server_string_for_hashing = (
        f"{safe_username}-{namespace}-{project}-{branch}-{commit_sha}"
    )
    safe_username_lowercase = safe_username.lower()
    if safe_username_lowercase[0].isalpha() and safe_username_lowercase[0].isascii():
        prefix = ""
    else:
        # NOTE: Username starts with an invalid character. This has to be modified because a
        # k8s service object cannot start with anything other than a lowercase alphabet character.
        # NOTE: We do not have worry about collisions with already existing servers from older
        # versions because the server name includes the hash of the original username, so the hash
        # would be different because the original username differs between someone whose username
        # is for example 7User vs. n7User.
        prefix = "n"
    return "{prefix}{username}-{project}-{hash}".format(
        prefix=prefix,
        username=safe_username_lowercase[:10],
        project=escapism.escape(project, escape_char="-")[:24].lower(),
        hash=md5(server_string_for_hashing.encode()).hexdigest()[:8].lower(),
    )
