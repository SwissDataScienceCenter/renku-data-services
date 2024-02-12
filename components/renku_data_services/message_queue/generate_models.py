"""Script to generate python models from avro schemas."""

import pathlib

import pyavro_gen.codewriters.core
import pyavro_gen.schema_and_classes_container
from avro_preprocessor.avro_paths import shutil


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


def generate_schemas():
    """Generate pythons files from avro."""
    from avro_preprocessor.avro_paths import AvroPaths
    from pyavro_gen.generator import AvroGenerator

    root = pathlib.Path(__file__).parent.resolve()
    schema_folder = root / "schemas"
    models_folder = root / "avro_models"

    AVRO_GENERATOR: AvroGenerator = AvroGenerator(
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

    AVRO_GENERATOR.process(None)
    # pyavro creates mock classes for tests that we don't need and that have broken imports anyways
    shutil.rmtree(root / "avro_models_test", ignore_errors=True)


generate_schemas()
