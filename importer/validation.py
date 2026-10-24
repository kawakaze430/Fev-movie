"""Public validation API shared by build and deployment checks."""
from .catalog import CatalogError, validate_catalog


def validate_public(document):
    validate_catalog(document, public=True)
    return document
