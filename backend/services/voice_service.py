"""Settings-backed speech selection. Invalid/disabled speech degrades to text."""
from domain.voice import VoiceConfig,VOICES
from security.logging import safe_event
class VoiceService:
    def __init__(self,repository):self.repository=repository
    def initialize(self,legacy_voice,legacy_rate):
        with self.repository.transaction(write=True) as unit:
            settings=unit.settings()
            if settings.get('assistant_name') and not settings.get('voice'):
                # Persist the existing deployment choice once; never silently replace it.
                value={'provider':'edge','voice_id':legacy_voice,'rate':legacy_rate,'pitch':'+0Hz','volume':'+0%','enabled':True}
                unit.save_settings({'voice':value},'system-voice-migration')
                unit.audit('system-voice-migration','settings.voice_migration','settings','general',settings,unit.settings(),'startup')
    def snapshot(self):
        with self.repository.transaction() as unit:value=unit.settings().get('voice',{})
        try:return VoiceConfig.model_validate(value).model_dump()
        except ValueError:
            safe_event('voice_configuration_degraded')
            return {'enabled':False}
    def public(self):
        with self.repository.transaction() as unit:value=unit.settings().get('voice',{})
        try:
            model=VoiceConfig.model_validate(value)
            return {**model.model_dump(),'status':'ready' if model.enabled else 'disabled'}
        except ValueError:return {'provider':'edge','enabled':False,'status':'degraded'}
    def catalogue(self):return VOICES
