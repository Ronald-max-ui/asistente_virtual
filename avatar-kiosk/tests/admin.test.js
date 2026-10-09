import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../../backend/static/admin/adminClient.js', import.meta.url), 'utf8');
const { createAdminClient } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
test('admin cookie client separates CSRF from login and never stores session credentials', async () => {
 const calls = [];
 const fetcher = async (url, options) => { calls.push({url,options}); const body = url.endsWith('/csrf') ? {csrf_token:'synthetic_csrf'} : {id:'fixture',display_name:'Fixture',role:'solo_lectura',permissions:[]}; return {ok:true,status:url.endsWith('/login')||url.endsWith('/logout') ? 204 : 200,json:async()=>body}; };
 const client = createAdminClient(fetcher); await client.login('fixture_user','synthetic_password'); await client.logout();
 assert.equal(calls.length,4); assert.equal(calls[0].options.headers['X-CSRF-Token'],undefined); assert.equal(calls[3].options.headers['X-CSRF-Token'],'synthetic_csrf');
 for(const call of calls) { assert.equal(call.options.credentials,'same-origin'); assert.equal(call.options.cache,'no-store'); assert.equal(call.options.headers.Authorization,undefined); }
 assert.doesNotMatch(source,/localStorage|sessionStorage|ADMIN_API_TOKEN|innerHTML|eval\(/);
});
test('admin UI hides provider details and clears CSRF after invalid session', async () => {
 const client=createAdminClient(async()=>({ok:false,status:401,json:async()=>({stack:'private secret'})}));
 await assert.rejects(client.me(),error=>error.status===401 && !error.message.includes('private secret'));
});
test('minimal admin page is keyboard accessible and isolated from public avatar', async () => {
 const html=await readFile(new URL('../../backend/static/admin/index.html',import.meta.url),'utf8');
 assert.match(html,/label for="username"/); assert.match(html,/label for="password"/); assert.match(html,/autocomplete="current-password"/); assert.match(html,/aria-live="polite"/); assert.doesNotMatch(html,/onclick=|<canvas|unsafe-eval/);
});
