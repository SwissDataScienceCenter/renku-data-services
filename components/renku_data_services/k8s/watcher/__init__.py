"""K8s watcher."""

from renku_data_services.k8s.watcher.core import K8sWatcher, k8s_object_handler

__all__ = ["K8sWatcher", "k8s_object_handler"]
