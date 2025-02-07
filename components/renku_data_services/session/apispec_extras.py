"""Extra definitions for the API spec."""

from renku_data_services.session.apispec import Build2, Build3

Build = Build2 | Build3
