"""Script to generate python models from avro schemas.

The library used here (pyavro_gen) is not very actively maintained and we need to patch quite a few things to get it to work.
There really isn't a good avro ->python code gen library that works with:
- namespaces
- references between schemas
- outputting somewhere other than the root of a project
Consider this library the least of all evils and we should switch it out as soon as possible.
If https://github.com/marcosschroh/dataclasses-avroschema/issues/552 ever gets adressed, this would be a good contender.
"""

import pathlib

import pyavro_gen.codewriters.core
import pyavro_gen.generation_classes
import pyavro_gen.modules.fields_collector
import pyavro_gen.schema_and_classes_container
from avro_preprocessor.preprocessor_module import PreprocessorModule

import shutil


# monkey patch writer to get correct namespaces
def getv(self):
    """Fake getter."""
    return "renku_data_services.message_queue.avro_models"


def setv(self, value) -> None:
    """Fake setter."""
    pass


def deletev(self):
    """Fake delete."""
    pass


pyavro_gen.schema_and_classes_container.SchemaAndClassesContainer.output_prefix = property(
    getv, setv, deletev, "output_prefix"
)

original_get_from_name = pyavro_gen.modules.fields_collector.FieldsCollector.get_class_writer_from_name


def _patched_get_class_writer_from_name(
    self, fully_qualified_name, writer_type=pyavro_gen.generation_classes.GenerationClassesType.RECORD_CLASS
):
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

class SchemaFixer(PreprocessorModule):
    """Removes _schema property from enums, which breaks avro serialization."""

    def __init__(self, schemas) -> None:
        super().__init__(schemas)

        self.writers = schemas.output_writers

        self.prefix = schemas.output_prefix


    def process(self) -> None:
        """Process all schemas."""

        for writer in self.writers.values():
            if not isinstance(writer,            pyavro_gen.generation_classes.GENERATION_CLASSES[
                pyavro_gen.generation_classes.GenerationClassesType.ENUM_CLASS
            ]):
                continue
            writer.attributes = [a for a in writer.attributes if a.name != "_schema"]



def generate_schemas():
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
    generator.available_preprocessing_modules[SchemaFixer.__name__]=SchemaFixer

    generator.process(["FieldsCollector","SchemaFixer", "AvscSchemaDependenciesChecker"])
    # pyavro creates mock classes for tests that we don't need and that have broken imports anyways
    shutil.rmtree(root / "avro_models_test", ignore_errors=True)


generate_schemas()
