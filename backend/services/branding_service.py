"""Immutable validated raster assets. SVG and arbitrary external URLs are forbidden."""
import hashlib,io,re,uuid,asyncio
from pathlib import Path
from dataclasses import replace
from PIL import Image
from fastapi import HTTPException
from services.voucher_service import read_validated_image
from security.storage import atomic_private_write
class BrandingService:
    def __init__(self,repository,root):self.repository=repository;self.root=Path(root).resolve()
    def list(self):return [self.public(r) for r in self.repository.list()]
    @staticmethod
    def public(row):return {key:row[key] for key in ('id','purpose','width','height')}|{'url':'/static/branding/'+row['filename']}
    async def upload(self,file,purpose,limits,actor,request_id):
        config=replace(limits,upload_max_bytes=2*1024*1024,image_max_pixels=4_000_000,image_max_dimension=2048)
        content,extension=await read_validated_image(file,config)
        with Image.open(io.BytesIO(content)) as image:width,height=image.size
        if purpose=='favicon' and (width>512 or height>512 or width!=height):raise HTTPException(422,'Favicon cuadrado de hasta 512 píxeles')
        if purpose=='favicon':
            with Image.open(io.BytesIO(content)) as image:
                buffer=io.BytesIO();image.convert('RGBA').save(buffer,format='PNG');content=buffer.getvalue();extension='.png'
        identifier=uuid.uuid4().hex;filename=identifier+extension
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        record={'id':identifier,'purpose':purpose,'filename':filename,'mime':{'.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'}[extension],'sha256':hashlib.sha256(content).hexdigest(),'width':width,'height':height}
        # One bounded worker completes write+registry together even if the HTTP client disconnects.
        # Files are immutable; a committed, unselected upload remains administratively visible.
        def store():
            atomic_private_write(self.root/filename,content)
            try:self.repository.add(record,actor,request_id)
            except BaseException:(self.root/filename).unlink(missing_ok=True);raise
        task=asyncio.create_task(asyncio.to_thread(store))
        try:await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        return self.public(record)
    def file(self,filename):
        if not re.fullmatch(r'[a-f0-9]{32}\.(?:png|jpg|webp)',filename):raise HTTPException(404)
        record=self.repository.get(filename)
        path=(self.root/filename).resolve()
        if not record or not path.is_relative_to(self.root) or not path.is_file():raise HTTPException(404)
        return path,record
