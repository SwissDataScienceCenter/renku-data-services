from dataclasses import dataclass, field
from typing import ClassVar, Dict, List

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
    def from_str(cls, val: str, required: bool = True):
        parts = val.split(cls._sep)
        if len(parts) != 2:
            raise ValueError(
                f"Expected to find prefix and name in the annotation but found {len(parts)} parts."
            )
        return cls(
            parts[0],
            parts[1],
            required,
        )


@dataclass
class _ServersGetEndpointAnnotations:
    renku_annotation_prefix: ClassVar[str] = "renku.io/"
    required_annotation_names: List[str] = field(
        default_factory=lambda: [
            "renku.io/namespace",
            "renku.io/projectName",
            "renku.io/branch",
            "renku.io/commit-sha",
            "renku.io/default_image_used",
            "renku.io/repository",
        ]
    )
    optional_annotation_names: List[str] = field(
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
            "jupyter.org/servername",
            "jupyter.org/username",
        ]
    )

    def __post_init__(self):
        annotations: List[_SessionAnnotationName] = []
        for annotation in self.required_annotation_names:
            annotations.append(_SessionAnnotationName.from_str(annotation, required=True))
        for annotation in self.optional_annotation_names:
            annotations.append(_SessionAnnotationName.from_str(annotation, required=False))
        self.annotations = annotations

        class _UserPodAnnotations(
            Schema.from_dict(
                {
                    annotation.get_field_name(sanitized=True): annotation.to_marshmallow_field()
                    for annotation in self.annotations
                }
            )
        ):
            class Meta:
                unknown = INCLUDE

        self.schema = _UserPodAnnotations

    def sanitize_dict(self, ann_dict: Dict[str, str]) -> Dict[str, str]:
        return self.schema().load(ann_dict)
