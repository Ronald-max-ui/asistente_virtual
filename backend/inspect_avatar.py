"""Read-only operator inventory. NOT a validator for untrusted VRM uploads."""
import argparse,io,json,struct
from pathlib import Path
from PIL import Image

def inspect(path):
    raw=Path(path).read_bytes()
    if len(raw)<20 or len(raw)>100*1024*1024:raise ValueError('Unsupported size')
    magic,version,total=struct.unpack_from('<4sII',raw)
    if magic!=b'glTF' or version!=2 or total!=len(raw):raise ValueError('Invalid GLB envelope')
    size,kind=struct.unpack_from('<II',raw,12)
    if kind!=0x4E4F534A or size>4*1024*1024:raise ValueError('Invalid JSON chunk')
    doc=json.loads(raw[20:20+size]);start=20+size;binary=b''
    if start+8<len(raw):
        length,kind=struct.unpack_from('<II',raw,start)
        if kind==0x004E4942:binary=raw[start+8:start+8+length]
    dimensions=[];external=[]
    for image in doc.get('images',[]):
        if 'uri' in image:external.append('external_or_data_uri');continue
        view=doc['bufferViews'][image['bufferView']];offset=view.get('byteOffset',0);length=view['byteLength']
        if offset+length>len(binary):raise ValueError('Buffer view outside bounds')
        with Image.open(io.BytesIO(binary[offset:offset+length])) as texture:dimensions.append(list(texture.size))
    return {'bytes':len(raw),'glb_version':version,'meshes':len(doc.get('meshes',[])),'primitives':sum(len(m.get('primitives',[])) for m in doc.get('meshes',[])),'materials':len(doc.get('materials',[])),'textures':len(doc.get('textures',[])),'texture_dimensions':dimensions,'morph_targets':sum(len(p.get('targets',[])) for m in doc.get('meshes',[]) for p in m.get('primitives',[])),'extensions_used':doc.get('extensionsUsed',[]),'extensions_required':doc.get('extensionsRequired',[]),'external_images':len(external),'upload_safe':False}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('file',type=Path);p.add_argument('--output',type=Path);args=p.parse_args();result=inspect(args.file);encoded=json.dumps(result,indent=2)
    if args.output:args.output.write_text(encoded+'\n',encoding='utf8')
    print(encoded)
if __name__=='__main__':main()
