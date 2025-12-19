"""Tests for the k8s models."""

from ulid import ULID

from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import GVK, K8sObject, K8sSecret


def test_k8s_object_not_render_manifest():
    obj = K8sObject(
        name="hello",
        namespace="ns1",
        cluster=ClusterId(ULID()),
        gvk=GVK(kind="kind", version="version1"),
        user_id="abc-user1",
        manifest={"not_a_real_manifest": "abd275c11ceb"},
    )
    sec = K8sSecret(
        name="hello",
        namespace="ns1",
        cluster=ClusterId(ULID()),
        gvk=GVK(kind="kind", version="version1"),
        user_id="abc-user1",
        manifest={"not_a_real_manifest": "abd275c11ceb"},
    )

    assert "abd275c11ceb" not in str(obj)
    assert "abd275c11ceb" not in repr(obj)
    assert "abd275c11ceb" not in str(sec)
    assert "abd275c11ceb" not in repr(sec)
