import datetime,hashlib,io,ipaddress,json,socket,time,warnings
import httpx
from PIL import Image
URLS=["https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0042-Maria-Suo-Suite-Dining-Area.jpg/HRBUB-P0042-Maria-Suo-Suite-Dining-Area.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0043-Maria-Suo-Suite-Living-Area.jpg/HRBUB-P0043-Maria-Suo-Suite-Living-Area.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0044-Maria-Suo-Suite-Spa-Area.jpg/HRBUB-P0044-Maria-Suo-Suite-Spa-Area.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0045-Cloudspire-Haven-Deluxe-King-Bed.jpg/HRBUB-P0045-Cloudspire-Haven-Deluxe-King-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0046-Cloudspire-Haven-Deluxe-King-Bed-Living-Room.jpg/HRBUB-P0046-Cloudspire-Haven-Deluxe-King-Bed-Living-Room.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0047-Cloudspire-Haven-Deluxe-Twin-Bed.jpg/HRBUB-P0047-Cloudspire-Haven-Deluxe-Twin-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0048-Cloudspire-Haven-Deluxe-Twin-Bed-Bathroom.jpg/HRBUB-P0048-Cloudspire-Haven-Deluxe-Twin-Bed-Bathroom.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0049-Maria-Suo-Suite-Bed.jpg/HRBUB-P0049-Maria-Suo-Suite-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0050-Dreamweaver-Room-Twin-Bed-Window-View.jpg/HRBUB-P0050-Dreamweaver-Room-Twin-Bed-Window-View.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0051-Luar-Ebrace-Suite-Twin-Bed.jpg/HRBUB-P0051-Luar-Ebrace-Suite-Twin-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0052-Luar-Ebrace-Suite-Twin-Bed-Bathroom.jpg/HRBUB-P0052-Luar-Ebrace-Suite-Twin-Bed-Bathroom.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0053-Luar-Ebrace-Suite-Twin-Bed-Living-Area.jpg/HRBUB-P0053-Luar-Ebrace-Suite-Twin-Bed-Living-Area.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0054-Dreamweaver-Room-One-Bed.jpg/HRBUB-P0054-Dreamweaver-Room-One-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0055-Dreamweaver-Room-One-Bed-Window-View.jpg/HRBUB-P0055-Dreamweaver-Room-One-Bed-Window-View.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0056-Dreamweaver-Room-Twin-Bed.jpg/HRBUB-P0056-Dreamweaver-Room-Twin-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0057-Dreamweaver-Room-Twin-Bed-Bathroom.jpg/HRBUB-P0057-Dreamweaver-Room-Twin-Bed-Bathroom.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0058-Stardust-Suite-Bathroom.jpg/HRBUB-P0058-Stardust-Suite-Bathroom.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0059-Stardust-Suite-Bed.jpg/HRBUB-P0059-Stardust-Suite-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0060-Stardust-Suite-Living-Area.jpg/HRBUB-P0060-Stardust-Suite-Living-Area.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0061-Sunset-Perch-Deluxe-Twin-Bed.jpg/HRBUB-P0061-Sunset-Perch-Deluxe-Twin-Bed.4x3.jpg","https://assets.hyatt.com/content/dam/hyatt/hyattdam/images/2025/03/17/2307/HRBUB-P0062-Sunset-Perch-Deluxe-Twin-Bed-Bathroom.jpg/HRBUB-P0062-Sunset-Perch-Deluxe-Twin-Bed-Bathroom.4x3.jpg"]
HEADERS={"User-Agent":"GO-Media-Harvester/6.1 (+rights-gated-cache)","Accept":"image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"}
MAX_BYTES=12*1024*1024
Image.MAX_IMAGE_PIXELS=40000000
warnings.simplefilter("error",Image.DecompressionBombWarning)
EXPECTED_FIRST={"sha256":"973ff3e051d5707dd29c5e88c3d137c0dbffb5f815a9ba45e803de4b1e2cba08","bytes":212140,"width":2560,"height":1920,"image_format":"WEBP"}
def fetch(url):
 from urllib.parse import urlsplit
 p=urlsplit(url)
 if p.scheme!="https" or p.hostname!="assets.hyatt.com" or p.port not in (None,443) or p.username or p.password:raise ValueError("URL_NOT_ALLOWLISTED")
 ips={x[4][0] for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)}
 if not ips or any(not ipaddress.ip_address(x).is_global for x in ips):raise ValueError("PUBLIC_DNS_REQUIRED")
 row={"source_url":url,"observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"request_headers":HEADERS}
 start=time.monotonic()
 with httpx.Client(trust_env=False,follow_redirects=False,timeout=12,headers=HEADERS) as client:
  with client.stream("GET",url) as response:
   row.update(http_status=response.status_code,resolved_url=str(response.url),response_content_type=response.headers.get("content-type"),response_vary=response.headers.get("vary"))
   if response.status_code!=200:raise ValueError("HTTP_STATUS_"+str(response.status_code))
   if response.headers.get("content-length") and int(response.headers["content-length"])>MAX_BYTES:raise ValueError("SIZE_LIMIT")
   chunks=[];size=0
   for chunk in response.iter_bytes():
    size+=len(chunk)
    if size>MAX_BYTES:raise ValueError("SIZE_LIMIT")
    if time.monotonic()-start>12:raise ValueError("TOTAL_REQUEST_DEADLINE")
    chunks.append(chunk)
 body=b"".join(chunks)
 with Image.open(io.BytesIO(body)) as im:
  im.load()
  if im.format not in ("JPEG","PNG","WEBP"):raise ValueError("FORMAT_NOT_ALLOWED")
  row.update(width=im.width,height=im.height,image_format=im.format)
 row.update(sha256=hashlib.sha256(body).hexdigest(),bytes=len(body),image_decode="PASS",status="PASS")
 return row
out={"schema":"GO_HK_PUBLIC_MEDIA_MEMORY_PREFLIGHT_V1","records":[],"first_asset_gate":"NOT_RUN","all_assets_gate":"NOT_RUN","persistent_writes":False}
for index,url in enumerate(URLS):
 try:
  row=fetch(url);row["index"]=index;out["records"].append(row)
  if index==0:
   if any(row[k]!=v for k,v in EXPECTED_FIRST.items()):
    out["first_asset_gate"]="HOLD_MISMATCH";break
   out["first_asset_gate"]="PASS"
 except Exception as exc:
  out["records"].append({"index":index,"source_url":url,"status":"FAILED","error_type":type(exc).__name__,"error":str(exc)[:120]})
  if index==0:out["first_asset_gate"]="HOLD_FETCH_FAILED"
  break
out["all_assets_gate"]="PASS" if out["first_asset_gate"]=="PASS" and len(out["records"])==21 and all(r["status"]=="PASS" for r in out["records"]) else "HOLD"
print(json.dumps(out,ensure_ascii=True))
