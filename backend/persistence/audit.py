"""Explicit snapshot allowlist: never arbitrary settings, passwords or files."""
import json,time,uuid
FIELDS={
 'programs':('id','name','kind','aliases','enabled','modalities','shifts','academic_path'),
 'prices':('id','program','modality','shift','concept','amount','currency','status','campaign_id','starts_on','ends_on','promotions'),
 'campaigns':('id','name','starts_on','ends_on','enabled'),
 'avatars':('id','name','url','active','enabled','thumbnail_url','description'),
 'settings':('assistant_name','active_avatar_id','logo_url','favicon_url','primary_color','kiosk_text_enabled','initial_message','voice'),
 'users':('id','username','display_name','role_id','enabled'),
 'vouchers':('voucher_id','status','reviewed_by','reviewed_at'),
 'sessions':(),
 'leads':('status','assigned_to_user_id','loss_reason','converted_at','converted_by','version'),
 'lead_tasks':('id','status','due_at','assigned_to','type'),
}
def snapshot(resource,data):
    if data is None: return None
    result={key:data[key] for key in FIELDS[resource] if key in data}
    if 'voice' in result:
        result['voice']={k:v for k,v in result['voice'].items() if k in ('provider','voice_id','rate','pitch','volume','enabled')}
    if 'promotions' in result:
        result['promotions']=[{k:p[k] for k in ('id','kind','value') if k in p} for p in result['promotions']]
    return result

def append_audit(db,actor,action,resource,identifier,before,after,request_id,now=None):
    record_id=uuid.uuid4().hex
    db.execute('INSERT INTO admin_audit_log VALUES(?,?,?,?,?,?,?,?,?,?)',(
        record_id,actor,action,resource,identifier,time.time() if now is None else now,request_id,'success',
        json.dumps(snapshot(resource,before),ensure_ascii=False),json.dumps(snapshot(resource,after),ensure_ascii=False)))
    return record_id

def decode_audit(row):
    result=dict(row)
    result['before']=json.loads(result.pop('before_json'))
    result['after']=json.loads(result.pop('after_json'))
    return result


def audit_where(filters=None,prefix=''):
    """Only allowlisted SQL identifiers; all filter values are bound parameters."""
    parts,values=[],[]
    for field,operator in [('actor_user_id','='),('action','='),('resource_type','='),('resource_id','='),('since','>='),('until','<=')]:
        value=(filters or {}).get(field)
        if value is not None:
            column='timestamp' if field in ('since','until') else field
            parts.append(prefix+column+operator+'?');values.append(value)
    return ('WHERE '+' AND '.join(parts) if parts else ''),values
