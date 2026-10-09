"""Additive runtime operations schema and transactional event helpers."""
import json,uuid,re
SCHEMA="""
CREATE TABLE IF NOT EXISTS lead_tracking(lead_id TEXT PRIMARY KEY REFERENCES leads(lead_id),status TEXT NOT NULL DEFAULT 'new',assigned_to_user_id TEXT,assigned_at REAL,loss_reason TEXT,converted_at REAL,converted_by TEXT,normalized_phone TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS lead_activity(id TEXT PRIMARY KEY,lead_id TEXT NOT NULL REFERENCES leads(lead_id),type TEXT NOT NULL,actor_user_id TEXT,created_at REAL NOT NULL,text TEXT NOT NULL DEFAULT '',data TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS lead_tasks(id TEXT PRIMARY KEY,lead_id TEXT NOT NULL REFERENCES leads(lead_id),assigned_to TEXT,due_at REAL NOT NULL,type TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','cancelled')),created_at REAL NOT NULL,completed_at REAL);
CREATE INDEX IF NOT EXISTS tracking_status ON lead_tracking(status,lead_id);
CREATE INDEX IF NOT EXISTS tracking_assignee ON lead_tracking(assigned_to_user_id,lead_id);
CREATE INDEX IF NOT EXISTS tracking_phone ON lead_tracking(normalized_phone,lead_id);
CREATE INDEX IF NOT EXISTS leads_created ON leads(created_at DESC,lead_id);
CREATE INDEX IF NOT EXISTS leads_program ON leads(program,created_at DESC);
CREATE INDEX IF NOT EXISTS activity_lead ON lead_activity(lead_id,created_at,id);
CREATE INDEX IF NOT EXISTS tasks_due ON lead_tasks(status,due_at,lead_id);
CREATE INDEX IF NOT EXISTS tasks_lead ON lead_tasks(lead_id,status,due_at);
CREATE INDEX IF NOT EXISTS voucher_status ON vouchers(status,created_at DESC);
CREATE INDEX IF NOT EXISTS voucher_lead ON vouchers(lead_id,created_at DESC);
"""
def normalized_phone(value):
    digits=re.sub(r'[^0-9]','',value)
    return digits[2:] if len(digits)==11 and digits.startswith('51') else digits

def activity(db,lead,type,actor,now,text='',data=None):
    identifier=uuid.uuid4().hex
    db.execute('INSERT INTO lead_activity VALUES(?,?,?,?,?,?,?)',(identifier,lead,type,actor,now,text,json.dumps(data or {})))
    return identifier

def seed(db,lead,phone,now):
    cursor=db.execute('INSERT OR IGNORE INTO lead_tracking(lead_id,normalized_phone,updated_at) VALUES(?,?,?)',(lead,normalized_phone(phone),now))
    if cursor.rowcount:activity(db,lead,'lead_created',None,now)
