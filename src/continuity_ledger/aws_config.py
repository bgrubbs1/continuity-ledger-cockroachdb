"""Secret-safe AWS runtime configuration for the managed deployment."""

from __future__ import annotations

from functools import lru_cache
import os
from typing import Any, Callable


@lru_cache(maxsize=1)
def resolve_database_url(
    client_factory: Callable[..., Any] | None = None,
) -> str:
    """Resolve the database URL without placing it in the SAM template.

    ``DATABASE_URL`` remains available for local verification.  Managed AWS
    deployments use an encrypted Standard parameter and grant the function
    access to that one parameter only.
    """

    direct = os.environ.get("DATABASE_URL", "")
    if direct:
        return direct
    parameter_name = os.environ.get("DATABASE_PARAMETER_NAME", "")
    if not parameter_name.startswith("/"):
        raise RuntimeError("DATABASE_PARAMETER_NAME must be an absolute SSM parameter name")
    if client_factory is None:
        import boto3

        client_factory = boto3.client
    response = client_factory("ssm").get_parameter(
        Name=parameter_name,
        WithDecryption=True,
    )
    value = response.get("Parameter", {}).get("Value", "")
    if not isinstance(value, str) or not value:
        raise RuntimeError("managed database parameter is empty")
    return value
