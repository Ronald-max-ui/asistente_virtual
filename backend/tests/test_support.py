"""Base temporal compartida por regresiones históricas; nunca modifica la base real."""
import atexit
import tempfile
from pathlib import Path
from migrate_commercial import migrate, seed_configuration
from persistence.sqlite_repository import SQLiteRepository
from services.pricing_service import pricing_service
from services.commercial_service import CommercialService

_directory = tempfile.TemporaryDirectory()
atexit.register(_directory.cleanup)
repository = SQLiteRepository(Path(_directory.name) / 'regressions.sqlite3')
report = migrate(repository)
if report['rejected']:
    raise RuntimeError('Catálogos de regresión inválidos: ' + str(report['rejected']))
seed_configuration(repository)
pricing_service.repository = repository
commercial_service = CommercialService(repository)
