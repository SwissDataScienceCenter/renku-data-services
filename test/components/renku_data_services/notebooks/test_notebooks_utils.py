import pytest

from renku_data_services.notebooks.crs import (
    NodeAffinity,
)
from renku_data_services.notebooks.utils import intersect_node_affinities

intersect_node_affinities_test_cases: list[tuple[NodeAffinity, NodeAffinity, NodeAffinity]] = [
    (
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {"matchExpressions": [{"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]}]}
                    ]
                }
            }
        ),
        NodeAffinity.model_validate({}),
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]},
                            ]
                        }
                    ]
                }
            }
        ),
    ),
    (
        NodeAffinity.model_validate({}),
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {"matchExpressions": [{"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]}]}
                    ]
                }
            }
        ),
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]},
                            ]
                        }
                    ]
                }
            }
        ),
    ),
    (
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {"matchExpressions": [{"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]}]}
                    ]
                }
            }
        ),
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [{"matchExpressions": [{"key": "renku.io/high-memory", "operator": "Exists"}]}]
                }
            }
        ),
        NodeAffinity.model_validate(
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
        ),
    ),
    (
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {"matchExpressions": [{"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]}]}
                    ]
                },
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "weight": 2,
                        "preference": {
                            "matchExpressions": [
                                {
                                    "key": "location",
                                    "operator": "In",
                                    "values": ["zone-A"],
                                }
                            ],
                        },
                    }
                ],
            }
        ),
        NodeAffinity.model_validate(
            {
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "weight": 1,
                        "preference": {
                            "matchExpressions": [
                                {
                                    "key": "disktype",
                                    "operator": "In",
                                    "values": ["ssd"],
                                }
                            ],
                        },
                    }
                ]
            }
        ),
        NodeAffinity.model_validate(
            {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {"key": "renku.io/node-purpose", "operator": "In", "values": ["user"]},
                            ]
                        }
                    ]
                },
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "weight": 2,
                        "preference": {
                            "matchExpressions": [
                                {
                                    "key": "location",
                                    "operator": "In",
                                    "values": ["zone-A"],
                                }
                            ],
                        },
                    },
                    {
                        "weight": 1,
                        "preference": {
                            "matchExpressions": [
                                {
                                    "key": "disktype",
                                    "operator": "In",
                                    "values": ["ssd"],
                                }
                            ],
                        },
                    },
                ],
            }
        ),
    ),
]


@pytest.mark.parametrize("left,right,expected", intersect_node_affinities_test_cases)
def test_intersect_node_affinities(left: NodeAffinity, right: NodeAffinity, expected: NodeAffinity) -> None:
    result = intersect_node_affinities(left, right)

    assert result.model_dump(mode="json") == expected.model_dump(mode="json")
    assert result == expected
