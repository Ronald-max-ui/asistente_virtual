"""Configuración pública mínima; sin notas ni información comercial interna."""
class AvatarService:
    def __init__(self, repository):
        self.repository = repository

    def public_config(self):
        with self.repository.transaction() as unit:
            settings = unit.settings()
            selected = next((a for a in unit.list('avatars') if a['active'] and a['enabled']), None)
            return {
                'assistant': {'name': settings.get('assistant_name', 'Lía')},
                'avatar': {key: selected[key] for key in ('id', 'name', 'url')} if selected else None,
                'visual': {key: settings[key] for key in ('logo_url', 'primary_color', 'initial_message')
                           if settings.get(key) is not None},
            }
