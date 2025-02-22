"""Static configuration."""

from dataclasses import dataclass, field
from typing import ClassVar, Self, cast

from marshmallow import INCLUDE, Schema, fields


@dataclass
class _SessionAnnotationName:
    prefix: str
    name: str
    required: bool
    _sep: ClassVar[str] = "/"

    def get_field_name(self, sanitized: bool = False) -> str:
        sep = "" if self.prefix.endswith(self._sep) else self._sep
        if sanitized:
            sanitized_prefix = self.prefix.replace(".", "_")
            sanitized_name = self.name.replace(".", "_")
            return f"{sanitized_prefix}{sep}{sanitized_name}"
        else:
            return f"{self.prefix}{sep}{self.name}"

    def to_marshmallow_field(self) -> fields.Str:
        return fields.Str(required=self.required, data_key=self.get_field_name())

    @classmethod
    def from_str(cls, val: str, required: bool = True) -> Self:
        parts = val.split(cls._sep)
        if len(parts) != 2:
            raise ValueError(f"Expected to find prefix and name in the annotation but found {len(parts)} parts.")
        return cls(
            parts[0],
            parts[1],
            required,
        )


@dataclass
class _ServersGetEndpointAnnotations:
    renku_annotation_prefix: ClassVar[str] = "renku.io/"
    required_annotation_names: list[str] = field(
        default_factory=lambda: [
            "renku.io/namespace",
            "renku.io/projectName",
            "renku.io/branch",
            "renku.io/commit-sha",
            "renku.io/default_image_used",
            "renku.io/repository",
        ]
    )
    optional_annotation_names: list[str] = field(
        default_factory=lambda: [
            "renku.io/hibernation",
            "renku.io/hibernationBranch",
            "renku.io/hibernationCommitSha",
            "renku.io/hibernationDirty",
            "renku.io/hibernationSynchronized",
            "renku.io/hibernationDate",
            "renku.io/hibernatedSecondsThreshold",
            "renku.io/lastActivityDate",
            "renku.io/idleSecondsThreshold",
            "renku.io/servername",
            "renku.io/username",
            "renku.io/git-host",
            "renku.io/gitlabProjectId",
            "renku.io/resourceClassId",
            "jupyter.org/servername",
            "jupyter.org/username",
            # Renku 2.0 annotations
            "renku.io/renkuVersion",
            "renku.io/launcherId",
            "renku.io/projectId",
        ]
    )

    def __post_init__(self) -> None:
        annotations: list[_SessionAnnotationName] = []
        for annotation in self.required_annotation_names:
            annotations.append(_SessionAnnotationName.from_str(annotation, required=True))
        for annotation in self.optional_annotation_names:
            annotations.append(_SessionAnnotationName.from_str(annotation, required=False))
        self.annotations = annotations

        self.schema = Schema.from_dict(
            {
                annotation.get_field_name(sanitized=True): annotation.to_marshmallow_field()
                for annotation in self.annotations
            }
        )(unknown=INCLUDE)

    def sanitize_dict(self, ann_dict: dict[str, str]) -> dict[str, str]:
        return cast(dict[str, str], self.schema.load(ann_dict))
