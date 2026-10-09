"""Public identity whitelist, compatibility visual keys and deterministic assets."""
from services.public_assets import asset_url
from services.voice_service import VoiceService
class AvatarService:
    def __init__(self,repository):self.repository=repository
    def public_config(self):
        with self.repository.transaction() as unit:
            settings=unit.settings();selected=next((a for a in unit.list('avatars') if a['active'] and a['enabled']),None)
        root=self.repository.path.parent/'branding'
        assistant={'name':settings.get('assistant_name','Lía'),'initial_message':settings.get('initial_message',''),'primary_color':settings.get('primary_color'),
            'logo_url':asset_url(settings.get('logo_url'),root),'favicon_url':asset_url(settings.get('favicon_url'),root)}
        avatar={key:selected[key] for key in ('id','name','url')} if selected else None
        if avatar:
            avatar['thumbnail_url']=asset_url(selected.get('thumbnail_url'),root)
            avatar['description']=selected.get('description','')
        return {'assistant':assistant,'avatar':avatar,'visual':{**{key:assistant[key] for key in ('logo_url','primary_color','initial_message','favicon_url')},'kiosk_text_enabled':settings.get('kiosk_text_enabled',False)},
            'voice':VoiceService(self.repository).public(),'features':{'kiosk_text_enabled':settings.get('kiosk_text_enabled',False)}}
