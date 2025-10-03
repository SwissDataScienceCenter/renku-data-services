from renku_data_services.notebooks.crs import (
    NodeAffinity,
)
from renku_data_services.notebooks.utils import intersect_node_affinities


def test_intersect_node_affinities() -> None:
    na_1 = NodeAffinity.model_validate(
        {
            "requiredDuringSchedulingIgnoredDuringExecution": {
                "nodeSelectorTerms": [
                    {"matchExpressions": [{"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]}]}
                ]
            }
        }
    )
    na_2 = NodeAffinity.model_validate(
        {
            "requiredDuringSchedulingIgnoredDuringExecution": {
                "nodeSelectorTerms": [{"matchExpressions": [{"key": "renku.io/high-memory", "operator": "Exists"}]}]
            }
        }
    )

    result = intersect_node_affinities(na_1, na_2)

    expected = NodeAffinity.model_validate(
        {
            "requiredDuringSchedulingIgnoredDuringExecution": {
                "nodeSelectorTerms": [
                    {
                        "matchExpressions": [
                            {"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]},
                            {"key": "renku.io/high-memory", "operator": "Exists"},
                        ]
                    }
                ]
            }
        }
    )

    assert result.model_dump(mode="json") == expected.model_dump(mode="json")
    assert result == expected
