/** Reproducible transfer inventory; run after npm run build. */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const html=fs.readFileSync(path.join(root,'dist/index.html'),'utf8');
const initial=new Set([...html.matchAll(/(?:src|href)="([^" ]+\.js)"/g)].map(match=>path.basename(match[1])));
const chunks=fs.readdirSync(path.join(root,'dist/assets')).filter(name=>name.endsWith('.js')).map(name=>{
 const data=fs.readFileSync(path.join(root,'dist/assets',name));
 return {name,bytes:data.length,gzip9_bytes:zlib.gzipSync(data,{level:9}).length,initial:initial.has(name)};
});
const result={chunks,initial_js_bytes:chunks.filter(x=>x.initial).reduce((n,x)=>n+x.bytes,0),
 initial_gzip9_bytes:chunks.filter(x=>x.initial).reduce((n,x)=>n+x.gzip9_bytes,0),total_js_bytes:chunks.reduce((n,x)=>n+x.bytes,0),
 largest_chunk_bytes:Math.max(...chunks.map(x=>x.bytes))};
console.log(JSON.stringify(result,null,2));
