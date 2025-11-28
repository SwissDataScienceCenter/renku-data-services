from io import StringIO

from yaml import safe_load

from renku_data_services.crc import models
from renku_data_services.crc.constants import DEFAULT_RUNTIME_PLATFORM
from renku_data_services.crc.server_options import (
    ServerOptions,
    ServerOptionsDefaults,
    generate_default_resource_pool,
)

server_options_yaml = """
defaultUrl:
  order: 1
  displayName: Default Environment
  type: enum
  default: /lab
  options: [/lab]
cpu_request:
  order: 2
  displayName: Number of CPUs
  type: enum
  default: 0.5
  options: [0.5, 1.0, 2.0, 3.0, 4.0]
mem_request:
  order: 3
  displayName: Amount of Memory
  type: enum
  default: 1G
  options: [1G, 2Gi, 4Gib]
disk_request:
  order: 4
  displayName: Amount of Storage
  type: enum
  default: "1G"
  options: ["1G", "10G"]
gpu_request:
  order: 5
  displayName: Number of GPUs
  type: enum
  default: 0
  options: [0, 1]
lfs_auto_fetch:
  order: 6
  displayName: Automatically fetch LFS data
  type: boolean
  default: false
"""

server_defaults_yaml = """
defaultUrl: /lab
cpu_request: 0.5
mem_request: 1G
disk_request: 1G
gpu_request: 0
lfs_auto_fetch: false
"""

expected_rp = models.UnsavedResourcePool(
    name="default",
    classes=[
        models.UnsavedResourceClass(
            name="small", cpu=0.5, memory=1, max_storage=10, gpu=0, default=False, default_storage=1
        ),
        models.UnsavedResourceClass(
            name="medium", cpu=1.0, memory=2, max_storage=10, gpu=1, default=False, default_storage=1
        ),
        models.UnsavedResourceClass(
            name="large", cpu=2.0, memory=4, max_storage=10, gpu=1, default=False, default_storage=1
        ),
        models.UnsavedResourceClass(
            name="xlarge", cpu=3.0, memory=4, max_storage=10, gpu=1, default=False, default_storage=1
        ),
        models.UnsavedResourceClass(
            name="xxlarge", cpu=4.0, memory=4, max_storage=10, gpu=1, default=False, default_storage=1
        ),
        models.UnsavedResourceClass(
            name="default", cpu=0.5, memory=1, max_storage=10, gpu=0, default=True, default_storage=1
        ),
    ],
    default=True,
    public=True,
    platform=DEFAULT_RUNTIME_PLATFORM,
)


def test_server_options_parsing() -> None:
    options = ServerOptions.model_validate(safe_load(StringIO(server_options_yaml)))
    defaults = ServerOptionsDefaults.model_validate(safe_load(StringIO(server_defaults_yaml)))
    rp = generate_default_resource_pool(options, defaults)
    assert rp == expected_rp
