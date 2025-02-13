"""Extra definitions for the API spec."""

from typing import Union

from pydantic import Field, RootModel

from renku_data_services.session.apispec import Build2, Build3


class Build(RootModel[Union[Build2, Build3]]):
    """A build."""

    root: Union[Build2, Build3] = Field(...)
