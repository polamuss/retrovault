"""Publish maintainer-approved fixed hardware photos as AVIF."""
import base64, hashlib, json, re
from io import BytesIO

def build_fixed_photos(out, folder, platforms, images):
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS=40_000_000
    known={p['name'] for p in platforms if p.get('category')!='logiciel'}
    count=0
    errors=[]
    for file in sorted(folder.glob('*.json')):
        try:
            if file.stat().st_size>2_000_000: raise ValueError('fichier trop volumineux')
            row=json.loads(file.read_text(encoding='utf-8'))
            name=row.get('name')
            if not isinstance(name,str) or name not in known: raise ValueError('matériel inconnu')
            if file.name!=hashlib.sha256(name.encode()).hexdigest()[:32]+'.json': raise ValueError('nom de fichier incorrect')
            if row.get('redistribution_authorized') is not True: raise ValueError('autorisation requise')
            credit=row.get('credit')
            if not isinstance(credit,str) or not credit.strip() or len(credit)>600: raise ValueError('crédit requis')
            value=row.get('image')
            if not isinstance(value,str): raise ValueError('image invalide')
            match=re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)',value)
            if not match: raise ValueError('format invalide')
            with Image.open(BytesIO(base64.b64decode(match[2],validate=True))) as raw:
                if raw.format not in ('JPEG','PNG','WEBP') or raw.width*raw.height>40_000_000: raise ValueError('format ou taille invalide')
                im=ImageOps.exif_transpose(raw).convert('RGBA')
                im.thumbnail((480,480),Image.Resampling.LANCZOS)
                buf=BytesIO()
                im.save(buf,format='AVIF',quality=55,speed=6)
                blob=buf.getvalue()
            rel='media/'+hashlib.sha256(blob).hexdigest()+'.avif'
            (out/rel).write_bytes(blob)
            key=json.dumps(['hardware',name],ensure_ascii=False,separators=(',',':'))
            images[key]={'path':rel,'credit':credit.strip(),'fixed':True}
            count+=1
        except Exception as exc:
            errors.append({'file':file.name,'error':str(exc)})
    return {'fixed_photos_published':count,'fixed_photo_errors':errors}
