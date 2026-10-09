"""Administrative operation orchestration; capture and pricing remain unchanged."""
import csv,io
from datetime import datetime,timezone
from domain.errors import DomainError
from domain.lead_operations import TRANSITIONS
from security.admin_policy import ROLES
class LeadOperationsService:
    def __init__(self,repository,users):self.repository=repository;self.users=users
    def assignees(self):return [{'id':u['id'],'display_name':u['display_name']} for u in self.users.list_users(100) if u['enabled'] and 'leads.write' in ROLES[u['role_id']]]
    def validate_assignee(self,identifier):
        if identifier is None:return
        try:user=self.users.get_user(identifier)
        except Exception:raise DomainError('assignee_invalid',422) from None
        if not user['enabled'] or 'leads.write' not in ROLES[user['role_id']]:raise DomainError('assignee_invalid',422)
    @staticmethod
    def filters(model):
        data=model.model_dump()
        for key in ('since','until'):
            if data[key]:data[key]=data[key].timestamp()
        if data['since'] is not None and data['until'] is not None and data['since']>=data['until']:raise DomainError('date_range_invalid',422)
        return data
    def names(self,rows):
        cache={}
        for row in rows:
            for idkey,namekey in [('assigned_to_user_id','assigned_name'),('actor_user_id','actor_name'),('reviewed_by','reviewer_name'),('assigned_to','assigned_name')]:
                identifier=row.get(idkey)
                if identifier:
                    if identifier not in cache:
                        try:cache[identifier]=self.users.get_user(identifier)['display_name']
                        except Exception:cache[identifier]='Usuario no disponible'
                    row[namekey]=cache[identifier]
        return rows
    def search(self,body,actor):return self.names(self.repository.search(self.filters(body),actor))
    def profile(self,id,permissions):
        data=self.repository.profile(id,'vouchers.read' in permissions);self.names([data]);self.names(data['activities']);self.names(data['tasks']);self.names(data.get('vouchers',[]));data['allowed_states']=sorted(TRANSITIONS[data['status']]);return data
    def mutate(self,id,kind,body,actor,request_id,expected,key,task=None):
        data=body.model_dump()
        if kind=='tracking':self.validate_assignee(data['assigned_to_user_id'])
        if kind=='task_create':self.validate_assignee(data['assigned_to']);data['due_at']=data['due_at'].timestamp()
        if task:data['task_id']=task
        from persistence.runtime_repository import RuntimeConflict
        try:return self.repository.mutate(id,kind,data,actor,request_id,expected,key)
        except RuntimeConflict as exc:raise DomainError(exc.code,exc.status) from None
    def export(self,body,actor,request_id):
        filters={**self.filters(body),'limit':1000,'offset':0};rows=self.repository.search(filters,actor)
        output=io.StringIO();writer=csv.writer(output);writer.writerow(['ID','Nombre','WhatsApp','Programa','Modalidad','Origen','Creado UTC','Estado','Responsable ID'])
        def safe(value):
            text='' if value is None else str(value)
            return "'"+text if text.lstrip().startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')) else text
        for r in rows:writer.writerow([safe(v) for v in [r['lead_id'],r['name'],r['whatsapp'],r['program'],r['modality'],r['origin'],datetime.fromtimestamp(r['created_at'],timezone.utc).isoformat(),r['status'],r['assigned_to_user_id']]])
        self.repository.audit_export(actor,request_id);return '\ufeff'+output.getvalue()
