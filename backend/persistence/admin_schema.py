"""Additive schema v2. Audit rows are append-only, including legacy actors."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_roles(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS admin_users(
 id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,
 password_hash TEXT NOT NULL,role_id TEXT NOT NULL REFERENCES admin_roles(id),enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 created_at REAL NOT NULL,updated_at REAL NOT NULL,last_login_at REAL,created_by TEXT,updated_by TEXT);
CREATE TABLE IF NOT EXISTS admin_sessions(
 id TEXT NOT NULL UNIQUE,token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES admin_users(id),csrf TEXT NOT NULL,
 created_at REAL NOT NULL,updated_at REAL NOT NULL,expires_at REAL NOT NULL,absolute_expires_at REAL NOT NULL,revoked_at REAL);
CREATE INDEX IF NOT EXISTS admin_sessions_user ON admin_sessions(user_id);
CREATE TABLE IF NOT EXISTS admin_audit_log(
 id TEXT PRIMARY KEY,actor_user_id TEXT,action TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT,
 timestamp REAL NOT NULL,request_id TEXT NOT NULL,result TEXT NOT NULL,before_json TEXT,after_json TEXT);
CREATE INDEX IF NOT EXISTS admin_audit_timestamp ON admin_audit_log(timestamp,id);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON admin_audit_log BEGIN SELECT RAISE(ABORT,'Immutable audit'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON admin_audit_log BEGIN SELECT RAISE(ABORT,'Immutable audit'); END;
"""
