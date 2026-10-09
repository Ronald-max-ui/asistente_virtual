"""Reglas administrativas independientes del motor de persistencia."""
from datetime import date
from domain.revision import check_revision
from persistence.models import ProgramRecord, PriceRecord, CampaignRecord, AvatarRecord, SettingsRecord
from domain.pricing import ProgramCatalog, CONCEPTOS
from services.consent_service import normalizar

MODELS = {'programs': ProgramRecord, 'prices': PriceRecord, 'campaigns': CampaignRecord, 'avatars': AvatarRecord}
AUDIT = {'created_at', 'updated_at', 'created_by', 'updated_by'}

def payload(record):
    return {key: value for key, value in record.items() if key not in AUDIT}

class ConfigurationConflict(ValueError):
    pass

def validate_configuration(unit):
    programs = {p['id']: ProgramRecord.model_validate(payload(p)) for p in unit.list('programs')}
    campaigns = {c['id']: CampaignRecord.model_validate(payload(c)) for c in unit.list('campaigns')}
    aliases = {}
    for p in programs.values():
        # Reutilizar validación de variantes y no introducir precios ficticios en la base.
        ProgramCatalog.model_validate(dict(schema_version=1, program=p.id, program_label=p.name,
            aliases=p.aliases, modalities=p.modalities, shifts=p.shifts,
            prices=[dict(concept='inscripcion', modality=None, shift=None, amount=None, currency='PEN',
                         status='pending', campaign='validation', starts_on=None, ends_on=None)]))
        for name in [p.id, p.id.replace('_', ' '), p.name, *p.aliases]:
            alias = normalizar(name)
            if not alias or (alias in aliases and aliases[alias] != p.id):
                raise ConfigurationConflict('Alias de programa vacío o ambiguo')
            aliases[alias] = p.id
    prices = [PriceRecord.model_validate(payload(p)) for p in unit.list('prices')]
    enabled = []
    for price in prices:
        program = programs.get(price.program)
        if not program:
            raise ConfigurationConflict('Programa de tarifa inexistente')
        if (price.modality is not None and price.modality not in program.modalities or
                price.shift is not None and price.shift not in program.shifts):
            raise ConfigurationConflict('La tarifa utiliza una modalidad o turno no registrado en su programa')
        if len({p.id for p in price.promotions}) != len(price.promotions):
            raise ConfigurationConflict('ID de promoción duplicado dentro de una tarifa')
        campaign = campaigns.get(price.campaign_id) if price.campaign_id else None
        if price.campaign_id and not campaign:
            raise ConfigurationConflict('Campaña inexistente')
        if price.status == 'inactive' or (campaign and not campaign.enabled):
            continue
        start = date.fromisoformat(campaign.starts_on) if campaign else price.starts_on or date.min
        end = date.fromisoformat(campaign.ends_on) if campaign else price.ends_on or date.max
        enabled.append((price, start, end))
    for index, (first, start, end) in enumerate(enabled):
        for second, other_start, other_end in enabled[index + 1:]:
            # Una oferta puede superponerse al precio base; dos bases u ofertas no.
            same_layer = bool(first.campaign_id) == bool(second.campaign_id)
            same_scope = (first.program == second.program and first.concept == second.concept and
                (first.modality is None or second.modality is None or first.modality == second.modality) and
                (first.shift is None or second.shift is None or first.shift == second.shift))
            if same_layer and same_scope and max(start, other_start) <= min(end, other_end):
                raise ConfigurationConflict(f'Tarifas/campañas superpuestas: {first.id} y {second.id}')

class CommercialService:
    def __init__(self, repository):
        self.repository = repository

    def list(self, resource):
        with self.repository.transaction() as unit:
            return unit.list(resource)

    def get(self, resource, identifier):
        with self.repository.transaction() as unit:
            return unit.get(resource, identifier)

    def save(self, resource, data, actor='admin-token', *, create=False, request_id='internal', expected=None):
        model = MODELS[resource].model_validate(data)
        with self.repository.transaction(write=True) as unit:
            previous = unit.get(resource, model.id)
            check_revision(previous, expected)
            previous_settings = unit.settings() if resource == 'avatars' else None
            if create and previous:
                raise ConfigurationConflict('El identificador ya existe')
            if resource == 'avatars' and model.active and not model.enabled:
                raise ConfigurationConflict('Un avatar deshabilitado no puede estar activo')
            result = unit.save(resource, model.id, model.model_dump(mode='json'), actor)
            if resource in ('programs', 'prices', 'campaigns'):
                validate_configuration(unit)
            if resource == 'avatars':
                selected = next((a['id'] for a in unit.list('avatars') if a['active']), None)
                if selected is None:
                    raise ConfigurationConflict('Selecciona otro avatar antes de desactivar el avatar activo')
                unit.save_settings({'active_avatar_id': selected}, actor)
                unit.audit(actor, 'settings.avatar', 'settings', 'general', previous_settings, unit.settings(), request_id)
            unit.audit(actor, resource + '.save', resource, model.id, previous, result, request_id)
            return result

    def settings(self):
        with self.repository.transaction() as unit:
            return unit.settings()

    def save_settings(self, data, actor='admin-token', *, request_id='internal', expected=None):
        model = SettingsRecord.model_validate(data)
        with self.repository.transaction(write=True) as unit:
            previous = unit.settings()
            for purpose,url in [('logo',model.logo_url),('favicon',model.favicon_url)]:
                if url and url.startswith('/static/branding/'):
                    # Same unit: keep reference checks and write in one transaction.
                    asset=unit.branding_asset(url.rsplit('/',1)[1])
                    if not asset or asset['purpose']!=purpose:raise ConfigurationConflict('Asset de branding no disponible')
            check_revision(previous, expected)
            if unit.list('avatars') and model.active_avatar_id is None:
                raise ConfigurationConflict('Debe seleccionarse un avatar activo')
            for avatar in unit.list('avatars'):
                target = avatar['id'] == model.active_avatar_id
                if target and not avatar['enabled']:
                    raise ConfigurationConflict('Avatar seleccionado deshabilitado')
                if avatar['active'] != target:
                    unit.save('avatars', avatar['id'], {**payload(avatar), 'active': target}, actor)
            if model.active_avatar_id and not unit.get('avatars', model.active_avatar_id):
                raise ConfigurationConflict('Avatar seleccionado inexistente')
            unit.save_settings(model.model_dump(mode='json'), actor)
            result = unit.settings()
            unit.audit(actor, 'settings.save', 'settings', 'general', previous, result, request_id)
            return result

    def activate_avatar(self, identifier, actor='admin-token', *, request_id='internal', expected=None):
        with self.repository.transaction(write=True) as unit:
            avatar = unit.get('avatars', identifier)
            if not avatar or not avatar['enabled']:
                raise ConfigurationConflict('Avatar inexistente o deshabilitado')
            previous_selection = unit.settings()
            check_revision(previous_selection, expected)
            result = unit.save('avatars', identifier, {**payload(avatar), 'active': True}, actor)
            unit.save_settings({'active_avatar_id': identifier}, actor)
            unit.audit(actor, 'avatars.activate', 'avatars', identifier, avatar, result, request_id)
            unit.audit(actor, 'settings.avatar', 'settings', 'general', previous_selection, unit.settings(), request_id)
            return result

    def save_campaign_offer(self, campaign, price, actor, request_id, *, create, expected_campaign=None, expected_price=None):
        """One transaction for campaign and selected offer; preserve other offers."""
        if not create and expected_campaign is None:
            from domain.errors import DomainError
            raise DomainError('admin_record_changed',409)
        campaign = CampaignRecord.model_validate(campaign)
        price = PriceRecord.model_validate(price)
        if price.campaign_id != campaign.id:
            raise ConfigurationConflict('Campaña inexistente')
        with self.repository.transaction(write=True) as unit:
            old_campaign = unit.get('campaigns', campaign.id)
            old_price = unit.get('prices', price.id)
            if not create and old_price and expected_price is None:
                from domain.errors import DomainError
                raise DomainError('admin_record_changed',409)
            check_revision(old_campaign, expected_campaign)
            check_revision(old_price, expected_price)
            if create and (old_campaign or old_price):
                raise ConfigurationConflict('El identificador ya existe')
            if not create and (not old_campaign or (old_price and old_price['campaign_id'] != campaign.id)):
                raise ConfigurationConflict('Campaña inexistente')
            new_campaign = unit.save('campaigns', campaign.id, campaign.model_dump(mode='json'), actor)
            new_price = unit.save('prices', price.id, price.model_dump(mode='json'), actor)
            validate_configuration(unit)
            unit.audit(actor, 'campaigns.save', 'campaigns', campaign.id, old_campaign, new_campaign, request_id)
            unit.audit(actor, 'prices.save', 'prices', price.id, old_price, new_price, request_id)
            return {'campaign':new_campaign,'price':new_price}
