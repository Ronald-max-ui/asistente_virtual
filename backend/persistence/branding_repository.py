"""Approved public branding registry; SQL remains in the adapter."""
import time
class BrandingRepository:
    def __init__(self,commercial):self.commercial=commercial
    def add(self,record,actor,request_id):
        with self.commercial.transaction(write=True) as unit:
            unit.db.execute('INSERT INTO branding_assets VALUES(?,?,?,?,?,?,?,?,?)',(record['id'],record['purpose'],record['filename'],record['mime'],record['sha256'],record['width'],record['height'],time.time(),actor))
            unit.audit(actor,'settings.asset_upload','settings',record['id'],None,None,request_id)
    def get(self,filename):
        with self.commercial.transaction() as unit:
            row=unit.db.execute('SELECT * FROM branding_assets WHERE filename=?',(filename,)).fetchone()
            return dict(row) if row else None
    def list(self):
        with self.commercial.transaction() as unit:return [dict(r) for r in unit.db.execute('SELECT * FROM branding_assets ORDER BY created_at DESC LIMIT 200')]
