"""Single RBAC policy; cookies contain no copied permissions."""
from dataclasses import dataclass
READ = frozenset(f'{r}.read' for r in ('programs','prices','campaigns','avatars','settings','leads','vouchers'))
ALL = READ | frozenset(f'{r}.write' for r in ('programs','prices','campaigns','avatars','settings','users')) | {'leads.write','leads.export','users.read','vouchers.review','audit.read','sessions.revoke'}
ROLES = {
 'superadmin': ALL,
 'administrador': frozenset(f'{r}.{verb}' for r in ('programs','prices','campaigns','avatars','settings') for verb in ('read','write')) | {'leads.read','leads.write','leads.export','audit.read'},
 'admisiones': frozenset(('leads.read','leads.write','programs.read','prices.read','campaigns.read')),
 'revisor_pagos': frozenset(('vouchers.read','vouchers.review')),
 'solo_lectura': READ,
}
@dataclass(frozen=True)
class AdminPrincipal:
    id: str | None
    display_name: str
    role: str
    session_hash: str | None = None
    @property
    def permissions(self): return ROLES[self.role]
    @property
    def actor(self): return self.id or 'legacy-token'
    def public(self): return dict(id=self.id, display_name=self.display_name, role=self.role, permissions=sorted(self.permissions))
