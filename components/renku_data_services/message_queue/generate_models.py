"""Script to generate python models from avro schemas."""

import json
import os
import pathlib

from dataclasses_avroschema import ModelGenerator

root = pathlib.Path(__file__).parent.resolve()
schema_folder = root / "schemas"
target = root / "models.py"

schemas = list()

for path, _, files in os.walk(schema_folder):
    for file in files:
        if not file.endswith("avsc"):
            continue
        with open(pathlib.Path(path) / file) as f:
            schemas.append(json.loads(f.read()))

model_generator = ModelGenerator()
result = model_generator.render_module(schemas=schemas)

with open(target) as f:
    f.write(result)
