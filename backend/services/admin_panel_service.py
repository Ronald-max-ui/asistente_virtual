"""Presentation data from existing services; no authorization or commercial rules duplicated."""
from pathlib import Path
import re
from domain.errors import DomainError
from domain.revision import revision

class AdminPanelService:
    def __init__(self,commercial,pricing,runtime,health):
        self.commercial,self.pricing,self.runtime,self.health=commercial,pricing,runtime,health
    def context(self,permissions):
        with self.commercial.repository.transaction() as unit:
            resources={key:unit.list(key) for key in ('programs','prices','campaigns','avatars') if key+'.read' in permissions}
            avatar_revision=revision(unit.settings()) if 'avatars.write' in permissions else None
        for price in resources.get('prices',[]):
            try:
                effective=self.pricing.resolve(price['program'],price['concept'],price['modality'],price['shift'])
                price['effective']={key:effective.get(key) for key in ('amount','currency','status','campaign','campaign_id','reason')}
            except ValueError:
                price['effective']=None
        today=self.pricing.today().isoformat()
        for campaign in resources.get('campaigns',[]):
            campaign['phase']='disabled' if not campaign['enabled'] else 'upcoming' if today<campaign['starts_on'] else 'ended' if today>campaign['ends_on'] else 'current'
        result={'today':today,'timezone':'America/Lima',**resources}
        if 'avatars.write' in permissions:result['avatar_revision']=avatar_revision
        return result
    def dashboard(self,permissions):
        context=self.context(permissions)
        result={}
        if 'programs' in context:result['active_programs']=sum(p['enabled'] for p in context['programs'])
        if 'campaigns' in context:result['current_campaigns']=sum(c['phase']=='current' for c in context['campaigns'])
        if 'avatars' in context:result['avatar']=next((a['name'] for a in context['avatars'] if a['active']),None)
        if {'leads.read','vouchers.read'} & permissions:
            counts=self.runtime.administrative_counts()
            if 'leads.read' in permissions:result['recent_leads']=counts['leads']
            if 'vouchers.read' in permissions:result['pending_vouchers']=counts['vouchers']
        health=self.health(self.commercial.repository,self.runtime)
        result['operational']=health['status']=='ready'
        result['knowledge']=health.get('knowledge',{}).get('status','invalid')
        return result
    def voucher_file(self,identifier,directory):
        voucher=self.runtime.get_record('vouchers',identifier)
        if not voucher:raise DomainError('admin_voucher_missing',404)
        reference=voucher['file_reference']
        if not re.fullmatch(r'[a-f0-9]{32}\.(png|jpg|webp)',reference):raise DomainError('admin_voucher_missing',404)
        root=Path(directory).resolve();path=(root/reference).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise DomainError('admin_voucher_missing',404)
        return path, {'.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'}[path.suffix]
