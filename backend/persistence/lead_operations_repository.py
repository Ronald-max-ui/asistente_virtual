"""SQLite adapter for tracking, filters, activity, tasks and exact aggregates."""
import json,time,uuid
from contextlib import closing
from datetime import datetime,timedelta,timezone
from domain.revision import revision
from domain.errors import DomainError
from domain.idempotency import fingerprint
from persistence.runtime_repository import RuntimeConflict
from persistence.lead_schema import activity,normalized_phone
from persistence.audit import append_audit
ZONE=timezone(timedelta(hours=-5))
SELECT="""SELECT l.lead_id,l.name,l.whatsapp,l.program,l.modality,l.origin,l.created_at,t.status,t.assigned_to_user_id,t.assigned_at,t.loss_reason,t.converted_at,t.converted_by,t.version,t.updated_at,s.funnel_stage AS stage,(SELECT min(due_at) FROM lead_tasks k WHERE k.lead_id=l.lead_id AND k.status='pending') AS next_follow_up_at,EXISTS(SELECT 1 FROM lead_tracking d WHERE d.normalized_phone=t.normalized_phone AND d.lead_id<>l.lead_id AND t.normalized_phone<>'') AS possible_duplicate FROM leads l JOIN lead_tracking t USING(lead_id) LEFT JOIN sessions s USING(session_id)"""
def boundaries(now):
    day=datetime.fromtimestamp(now,ZONE).replace(hour=0,minute=0,second=0,microsecond=0)
    return day.timestamp(),(day+timedelta(days=1)).timestamp(),(day+timedelta(days=2)).timestamp()
class LeadOperationsRepository:
    def __init__(self,runtime):self.runtime=runtime
    def _row(self,db,id):
        row=db.execute('SELECT * FROM lead_tracking WHERE lead_id=?',(id,)).fetchone()
        if not row:raise DomainError('lead_not_found',404)
        return dict(row)
    @staticmethod
    def etag(row):return revision({'lead_id':row['lead_id'],'version':row['version']})
    def _expected(self,row,expected):
        if expected!=self.etag(row):raise DomainError('lead_changed',409)
    def where(self,filters,actor):
        pieces=[];values=[]
        for key,column in [('status','t.status'),('program','l.program'),('modality','l.modality'),('assigned_to','t.assigned_to_user_id')]:
            if filters.get(key):pieces.append(column+'=?');values.append(filters[key])
        for key,op in [('since','>='),('until','<')]:
            if filters.get(key) is not None:pieces.append('l.created_at'+op+'?');values.append(filters[key])
        quick=filters.get('quick','all');today,tomorrow,nextday=boundaries(self.runtime.clock())
        if quick in ('new','converted','lost'):pieces.append('t.status=?');values.append(quick)
        if quick=='mine':pieces.append('t.assigned_to_user_id=?');values.append(actor)
        if quick in ('today','overdue','tomorrow'):
            condition='k.due_at<?' if quick=='overdue' else 'k.due_at>=? AND k.due_at<?'
            pieces.append("EXISTS(SELECT 1 FROM lead_tasks k WHERE k.lead_id=l.lead_id AND k.status='pending' AND "+condition+')')
            values.extend([self.runtime.clock()] if quick=='overdue' else [today,tomorrow] if quick=='today' else [tomorrow,nextday])
        term=filters.get('search','').strip()
        if term:
            escape=lambda v:v.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            phone=normalized_phone(term);pieces.append("(l.name LIKE ? ESCAPE '\\'"+(" OR t.normalized_phone LIKE ? ESCAPE '\\')" if phone else ')'));values.append('%'+escape(term)+'%')
            if phone:values.append('%'+escape(phone)+'%')
        return (' WHERE '+' AND '.join(pieces) if pieces else ''),values
    def search(self,filters,actor):
        where,values=self.where(filters,actor)
        with closing(self.runtime.connect()) as db:return [dict(r) for r in db.execute(SELECT+where+' ORDER BY l.created_at DESC,l.lead_id LIMIT ? OFFSET ?',(*values,filters.get('limit',21),filters.get('offset',0)))]
    def profile(self,id,include_vouchers=False):
        with closing(self.runtime.connect()) as db:
            db.execute('BEGIN')
            row=self._row(db,id);lead=dict(db.execute(SELECT+' WHERE l.lead_id=?',(id,)).fetchone())
            lead['etag']=self.etag(row)
            lead['activities']=[{**dict(a),'data':json.loads(a['data'])} for a in db.execute('SELECT * FROM lead_activity WHERE lead_id=? ORDER BY created_at DESC,id DESC LIMIT 100',(id,))]
            lead['tasks']=[dict(t) for t in db.execute("SELECT * FROM lead_tasks WHERE lead_id=? ORDER BY (status='pending') DESC,due_at,id LIMIT 100",(id,))]
            if include_vouchers:lead['vouchers']=[dict(v) for v in db.execute('SELECT v.voucher_id,v.program,v.concept,v.amount,v.currency,v.created_at,v.status,r.reviewed_by,r.reviewed_at FROM vouchers v LEFT JOIN voucher_reviews r USING(voucher_id) WHERE lead_id=? ORDER BY v.created_at DESC LIMIT 100',(id,))]
            return lead
    def activities(self,id,limit,offset):
        with closing(self.runtime.connect()) as db:
            self._row(db,id)
            return [{**dict(row),'data':json.loads(row['data'])} for row in db.execute('SELECT * FROM lead_activity WHERE lead_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(id,limit,offset))]
    def mutate(self,id,kind,data,actor,request_id,expected,key):
        audit_before=audit_after=None;audit_resource='leads';audit_id=id;audit_action='leads.'+kind
        now=self.runtime.clock();digest=fingerprint({'actor':actor,'kind':kind,'data':data})
        with self.runtime.transaction() as db:
            replay=self.runtime._replay(db,'admin:'+id+':'+actor,kind,key,digest)
            if replay is not None:return replay
            row=self._row(db,id);self._expected(row,expected)
            if kind=='tracking':
                from domain.lead_operations import TRANSITIONS
                status=data['status']
                if status!=row['status'] and status not in TRANSITIONS[row['status']]:raise DomainError('lead_transition',409)
                if status=='lost' and data.get('loss_reason')=='other' and not data.get('loss_note') and (row['status']!='lost' or row['loss_reason']!='other'):raise DomainError('loss_note_required',422)
                assigned=data.get('assigned_to_user_id');converted_at=row['converted_at'];converted_by=row['converted_by']
                if status=='converted' and row['status']!='converted':converted_at=now;converted_by=actor
                db.execute('UPDATE lead_tracking SET status=?,assigned_to_user_id=?,assigned_at=?,loss_reason=?,converted_at=?,converted_by=? WHERE lead_id=?',(status,assigned,(now if assigned else None) if assigned!=row['assigned_to_user_id'] else row['assigned_at'],data.get('loss_reason') if status=='lost' else None,converted_at,converted_by,id))
                if assigned!=row['assigned_to_user_id']:activity(db,id,'assigned',actor,now,data={'assigned_to_user_id':assigned})
                if status=='lost' and row['status']=='lost' and (data.get('loss_reason')!=row['loss_reason'] or data.get('loss_note')):activity(db,id,'loss_updated',actor,now,data.get('loss_note',''),{'loss_reason':data.get('loss_reason')})
                if status!=row['status']:activity(db,id,'converted' if status=='converted' else 'status_changed',actor,now,data.get('loss_note','') if status=='lost' else '',{'before':row['status'],'status':status,'loss_reason':data.get('loss_reason') if status=='lost' else None})
            elif kind=='activity':
                activity(db,id,data['type'],actor,now,data['text']);audit_action='leads.'+data['type']
            elif kind=='task_create':
                task_id=uuid.uuid4().hex;db.execute('INSERT INTO lead_tasks VALUES(?,?,?,?,?,?,?,?,?)',(task_id,id,data.get('assigned_to'),data['due_at'],data['type'],data['note'],'pending',now,None))
                activity(db,id,'task_created',actor,now,data={'task_id':task_id,'due_at':data['due_at']})
                audit_resource='lead_tasks';audit_id=task_id;audit_action='leads.task_created';audit_after=dict(db.execute('SELECT * FROM lead_tasks WHERE id=?',(task_id,)).fetchone())
            elif kind=='task_update':
                task=db.execute('SELECT * FROM lead_tasks WHERE id=? AND lead_id=?',(data['task_id'],id)).fetchone()
                if not task:raise DomainError('task_not_found',404)
                if task['status']!='pending':raise DomainError('task_transition',409)
                db.execute('UPDATE lead_tasks SET status=?,completed_at=? WHERE id=?',(data['status'],now,data['task_id']))
                activity(db,id,'task_'+data['status'],actor,now,data={'task_id':data['task_id']})
                audit_resource='lead_tasks';audit_id=data['task_id'];audit_action='leads.task_'+data['status'];audit_before=dict(task);audit_after=dict(db.execute('SELECT * FROM lead_tasks WHERE id=?',(audit_id,)).fetchone())
            else:raise ValueError('Unsupported operation')
            db.execute('UPDATE lead_tracking SET version=version+1,updated_at=? WHERE lead_id=?',(now,id))
            final=self._row(db,id);append_audit(db,actor,audit_action,audit_resource,audit_id,audit_before if audit_resource=='lead_tasks' else row,audit_after if audit_resource=='lead_tasks' else final,request_id,now)
            result={'lead_id':id,'etag':self.etag(final),'status':'ok'}
            self.runtime._record(db,'admin:'+id+':'+actor,kind,key,digest,result);return result
    def aggregates(self,period='7d'):
        now=self.runtime.clock();today,tomorrow,_=boundaries(now)
        start=today-6*86400 if period=='7d' else today-29*86400 if period=='30d' else datetime.fromtimestamp(now,ZONE).replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp()
        with closing(self.runtime.connect()) as db:
            db.execute('BEGIN');scalar=lambda sql,args=():db.execute(sql,args).fetchone()[0]
            result={'new_today':scalar('SELECT count(*) FROM leads WHERE created_at>=? AND created_at<?',(today,tomorrow)),'new_7_days':scalar('SELECT count(*) FROM leads WHERE created_at>=? AND created_at<?',(today-6*86400,tomorrow)),'follow_ups_today':scalar("SELECT count(DISTINCT lead_id) FROM lead_tasks WHERE status='pending' AND due_at>=? AND due_at<?",(today,tomorrow)),'overdue':scalar("SELECT count(DISTINCT lead_id) FROM lead_tasks WHERE status='pending' AND due_at<?",(now,)),'created_in_period':scalar('SELECT count(*) FROM leads WHERE created_at>=? AND created_at<?',(start,tomorrow)),'conversions_in_period':scalar('SELECT count(*) FROM lead_tracking WHERE converted_at>=? AND converted_at<?',(start,tomorrow)),'timezone':'America/Lima','period':period}
            for key,column in [('by_program','l.program'),('by_origin','l.origin'),('by_status','t.status')]:result[key]=[dict(r) for r in db.execute('SELECT '+column+' AS label,count(*) AS count FROM leads l JOIN lead_tracking t USING(lead_id) WHERE l.created_at>=? AND l.created_at<? GROUP BY '+column,(start,tomorrow))]
            result['conversions_by_program']=[dict(r) for r in db.execute('SELECT l.program AS label,count(*) AS count FROM leads l JOIN lead_tracking t USING(lead_id) WHERE t.converted_at>=? AND t.converted_at<? GROUP BY l.program',(start,tomorrow))]
            result['voucher_counts']={r['status']:r['count'] for r in db.execute('SELECT status,count(*) AS count FROM vouchers GROUP BY status')};return result
    def audit_export(self,actor,request_id):
        with self.runtime.transaction() as db:append_audit(db,actor,'leads.export','leads',uuid.uuid4().hex,None,None,request_id,self.runtime.clock())
