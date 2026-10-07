"""Migración explícita e idempotente. Los sidecars son una fuente temporal, no runtime."""
import argparse
import hashlib
import json
import shutil
from decimal import Decimal
from pathlib import Path
from persistence.models import ProgramRecord, PriceRecord, CampaignRecord, AvatarRecord, SettingsRecord
from persistence.sqlite_repository import SQLiteRepository
from services.commercial_service import validate_configuration
from services.pricing_service import ProgramCatalog, _unique_object
from commercial_runtime import BASE, database_path

def migrate(repository, knowledge_dir=BASE / 'knowledge'):
    root = Path(knowledge_dir).resolve()
    report = {'imported': [], 'skipped': [], 'rejected': [], 'programs': 0, 'prices': 0, 'campaigns': 0}
    paths = sorted(root.glob('*/*.pricing.json'))
    if not paths:
        report['rejected'].append({'file': str(root), 'reason': 'No se encontraron sidecars de migración'})
    for path in paths:
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError('Archivo fuera del directorio de migración')
            raw = path.read_bytes()
            catalog = ProgramCatalog.model_validate(json.loads(raw.decode('utf-8-sig'), parse_float=Decimal,
                                                               object_pairs_hook=_unique_object))
            if path.name != catalog.program + '.pricing.json':
                raise ValueError('ID distinto del nombre de archivo')
            key = 'pricing-json:v1:' + catalog.program
            with repository.transaction(write=True) as unit:
                if unit.migration_applied(key):
                    report['skipped'].append({'program': catalog.program, 'reason': 'Ya migrado; no se sobrescriben cambios administrativos'})
                    continue
                if unit.get('programs', catalog.program):
                    raise ValueError('Programa existente sin marca de migración; requiere conciliación manual')
                program = ProgramRecord(id=catalog.program, name=catalog.program_label,
                    kind='curso_corto' if path.parent.name == '03_cursos_cortos' else 'carrera_tecnica',
                    aliases=catalog.aliases, modalities=catalog.modalities, shifts=catalog.shifts,
                    academic_path=str(path.relative_to(root)).replace('\\', '/').replace('.pricing.json', '.md'))
                unit.save('programs', program.id, program.model_dump(mode='json'), 'migration')
                campaign_count = 0
                campaign_ids = set()
                for index, entry in enumerate(catalog.prices):
                    data = entry.model_dump(mode='json')
                    campaign_id = None
                    if data['starts_on'] and data['ends_on']:
                        identity = catalog.program + ':' + data['campaign'] + ':' + data['starts_on'] + ':' + data['ends_on']
                        campaign_id = 'migration_' + hashlib.sha256(identity.encode()).hexdigest()[:20]
                        if campaign_id not in campaign_ids:
                            campaign = CampaignRecord(id=campaign_id, name=data['campaign'],
                                starts_on=data['starts_on'], ends_on=data['ends_on'])
                            unit.save('campaigns', campaign_id, campaign.model_dump(mode='json'), 'migration')
                            campaign_ids.add(campaign_id)
                            campaign_count += 1
                        data.update(starts_on=None, ends_on=None)
                    price = PriceRecord.model_validate({**data, 'id': f'{catalog.program}_{index:03d}_{entry.concept}',
                                                        'program': catalog.program, 'campaign_id': campaign_id})
                    unit.save('prices', price.id, price.model_dump(mode='json'), 'migration')
                validate_configuration(unit)
                unit.record_migration(key, hashlib.sha256(raw).hexdigest())
            report['imported'].append({'program': catalog.program, 'prices': len(catalog.prices), 'campaigns': campaign_count})
            report['programs'] += 1
            report['prices'] += len(catalog.prices)
            report['campaigns'] += campaign_count
        except (ValueError, OSError) as exc:
            report['rejected'].append({'file': path.name, 'reason': str(exc)})
    return report

def seed_configuration(repository):
    with repository.transaction(write=True) as unit:
        if not unit.list('avatars'):
            avatar = AvatarRecord(id='lia_original', name='Lía Original', url='/static/avatars/lia_original.vrm', active=True)
            unit.save('avatars', avatar.id, avatar.model_dump(mode='json'), 'migration')
        if not unit.settings():
            active = next((a['id'] for a in unit.list('avatars') if a['active']), None)
            settings = SettingsRecord(assistant_name='Lía', active_avatar_id=active)
            unit.save_settings(settings.model_dump(mode='json'), 'migration')

def copy_original_avatar():
    source = BASE.parent / 'avatar-kiosk' / 'public' / 'avatar.vrm'
    target = BASE / 'static' / 'avatars' / 'lia_original.vrm'
    if not target.exists():
        if not source.is_file():
            raise ValueError('Falta el avatar original; colocar static/avatars/lia_original.vrm antes de servir la configuración')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=database_path())
    parser.add_argument('--knowledge', type=Path, default=BASE / 'knowledge')
    parser.add_argument('--skip-avatar-copy', action='store_true', help='Sólo para validación/pruebas con assets provisionados aparte')
    args = parser.parse_args()
    repository = SQLiteRepository(args.database)
    report = migrate(repository, args.knowledge)
    if not report['rejected']:
        try:
            if not args.skip_avatar_copy:
                copy_original_avatar()
            seed_configuration(repository)
        except (ValueError, OSError) as exc:
            report['rejected'].append({'file': 'initial_configuration', 'reason': str(exc)})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report['rejected'] else 0

if __name__ == '__main__':
    raise SystemExit(main())
