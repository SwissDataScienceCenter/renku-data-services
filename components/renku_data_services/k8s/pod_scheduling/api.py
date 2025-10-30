"""Models to use for validating API requests and responses."""

from pydantic import RootModel

from renku_data_services.notebooks.cr_amalthea_session import Affinity, Toleration


class AffinityField(RootModel[Affinity | None]):
    """Affinity field."""

    root: Affinity | None = None


class NodeSelectorField(RootModel[dict[str, str] | None]):
    """Node selector field."""

    root: dict[str, str] | None = None


class TolerationsField(RootModel[list[Toleration] | None]):
    """Tolerations field."""

    root: list[Toleration] | None = None
