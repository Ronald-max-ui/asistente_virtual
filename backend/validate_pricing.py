"""Validación comercial sin red, servidor ni regeneración de ChromaDB."""
from services.pricing_service import pricing_service, CatalogError


if __name__ == "__main__":
    try:
        catalogs = pricing_service.catalogs()
        for program, catalog in catalogs.items():
            print(f"OK {program}: {len(catalog.prices)} tarifas validadas")
    except CatalogError as error:
        print(f"ERROR: {error}")
        raise SystemExit(1)
