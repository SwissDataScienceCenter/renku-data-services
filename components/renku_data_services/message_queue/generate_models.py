"""Script to generate python models from avro schemas.

The library used here (pyavro_gen) is not very actively maintained and we need to patch quite a few things to get it to
work.
There really isn't a good avro ->python code gen library that works with:
- namespaces
- references between schemas
- outputting somewhere other than the root of a project
Consider this library the least of all evils and we should switch it out as soon as possible.
If https://github.com/marcosschroh/dataclasses-avroschema/issues/552 ever gets adressed, this would be a good
contender.
"""

import pathlib
import shutil
from collections import OrderedDict

import pyavro_gen.codewriters.core
import pyavro_gen.generation_classes
import pyavro_gen.modules.fields_collector
import pyavro_gen.schema_and_classes_container
from avro_preprocessor.avro_domain import Avro
from avro_preprocessor.preprocessor_module import PreprocessorModule
from pyavro_gen import generation_classes
from pyavro_gen.codewriters.utils import namespace_name
from pyavro_gen.modules.avsc_schema_dependency_checker import AvscSchemaDependenciesChecker


# monkey patch writer to get correct namespaces
def getv(self) -> str:  # type: ignore[no-untyped-def]
    """Fake getter."""
    return "renku_data_services.message_queue.avro_models"


def setv(self, value) -> None:  # type: ignore[no-untyped-def]
    """Fake setter."""
    pass


def deletev(self) -> None:  # type: ignore[no-untyped-def]
    """Fake delete."""
    pass


pyavro_gen.schema_and_classes_container.SchemaAndClassesContainer.output_prefix = property(
    getv, setv, deletev, "output_prefix"
)

original_get_from_name = pyavro_gen.modules.fields_collector.FieldsCollector.get_class_writer_from_name


def _patched_get_class_writer_from_name(
    self: pyavro_gen.modules.fields_collector.FieldsCollector,
    fully_qualified_name: str,
    writer_type: generation_classes.GenerationClassesType = generation_classes.GenerationClassesType.RECORD_CLASS,
) -> pyavro_gen.codewriters.core.ClassWriter:
    """Patched version that properly handles enum references."""
    if (
        fully_qualified_name in self.writers
        and isinstance(
            self.writers[fully_qualified_name],
            pyavro_gen.generation_classes.GENERATION_CLASSES[
                pyavro_gen.generation_classes.GenerationClassesType.ENUM_CLASS
            ],
        )
        and writer_type == pyavro_gen.generation_classes.GenerationClassesType.RECORD_CLASS
    ):
        writer_type = pyavro_gen.generation_classes.GenerationClassesType.ENUM_CLASS
    return original_get_from_name(self, fully_qualified_name, writer_type)


pyavro_gen.modules.fields_collector.FieldsCollector.get_class_writer_from_name = _patched_get_class_writer_from_name


class SchemaFixer(PreprocessorModule):  # type: ignore[misc]
    """Removes _schema property from enums, which breaks avro serialization."""

    def __init__(self, schemas) -> None:  # type: ignore[no-untyped-def]
        super().__init__(schemas)

        self.writers = schemas.output_writers

        self.prefix = schemas.output_prefix

    def process(self) -> None:
        """Process all schemas."""

        for writer in self.writers.values():
            if not isinstance(
                writer,
                pyavro_gen.generation_classes.GENERATION_CLASSES[
                    pyavro_gen.generation_classes.GenerationClassesType.ENUM_CLASS
                ],
            ):
                continue
            writer.attributes = [a for a in writer.attributes if a.name != "_schema"]


class DependencyChecker(AvscSchemaDependenciesChecker):  # type: ignore[misc]
    """Fixes dependency checks."""

    def store_dependencies_of_field(self, node: Avro.Node) -> None:
        """Store external_dependencies of other records in a node in a private dict."""

        if isinstance(node, str) and self.ancestors and "." in node:
            anc = self.ancestors[-1].key
            if anc == Avro.Type or isinstance(anc, int):
                dependent_ancestor = self._find_ancestor()
                if dependent_ancestor:
                    self.record_dependencies_graph.add_edge(dependent_ancestor, node)

        if isinstance(node, OrderedDict) and Avro.Name in node:
            if Avro.Namespace in node:
                dep = node[Avro.Namespace] + "." + node[Avro.Name]
            elif "." in node[Avro.Name]:
                dep = node[Avro.Name]
            elif Avro.Fields in node or Avro.Symbols in node:
                dep = namespace_name(self.current_schema_name) + "." + node[Avro.Name]
            else:
                return

            dependent_ancestor = self._find_ancestor()
            self.record_dependencies_graph.add_edge(dependent_ancestor, dep)

    def process(self) -> None:
        """Detects all dependencies among schemas."""
        super().process()

        # sort schemas by dependencies
        keys = list(self.schemas.output_writers.keys())
        keys = sorted(keys)
        for _idx, (record, dependencies) in enumerate(sorted(self.record_dependencies.items())):
            if len(dependencies) == 0:
                continue
            record_index = keys.index(record)
            for dep in dependencies:
                dep_index = keys.index(dep)
                if dep_index <= record_index:
                    continue
                keys[dep_index], keys[record_index] = keys[record_index], keys[dep_index]
                record_index = dep_index

        self.schemas.output_writers = OrderedDict((key, self.schemas.output_writers[key]) for key in keys)


def generate_schemas() -> None:
    """Generate pythons files from avro."""

    from avro_preprocessor.avro_paths import AvroPaths
    from pyavro_gen.generator import AvroGenerator

    root = pathlib.Path(__file__).parent.resolve()
    schema_folder = root / "schemas"
    models_folder = root / "avro_models"

    generator: AvroGenerator = AvroGenerator(
        AvroPaths(
            input_path=str(schema_folder),
            output_path=str(models_folder),
            base_namespace="io.renku",
            types_namespace=None,
            rpc_namespace=None,
            input_schema_file_extension="avsc",
        ),
        verbose=True,
    )
    generator.preprocessing_modules.append(SchemaFixer)
    generator.available_preprocessing_modules[SchemaFixer.__name__] = SchemaFixer
    generator.preprocessing_modules.append(DependencyChecker)
    generator.available_preprocessing_modules[DependencyChecker.__name__] = DependencyChecker

    generator.process(["FieldsCollector", "SchemaFixer", "DependencyChecker", "AvscSchemaDependenciesChecker"])
    # pyavro creates mock classes for tests that we don't need and that have broken imports anyways
    shutil.rmtree(root / "avro_models_test", ignore_errors=True)


generate_schemas()
