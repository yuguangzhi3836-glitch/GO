import base64,hashlib
from pathlib import Path
root=Path('evidence')
for p in sorted(root.iterdir()):
    if p.suffix not in {'.json','.log'}:continue
    data=p.read_bytes()
    print('GO_EVIDENCE_FILE_BEGIN',p.name,len(data),hashlib.sha256(data).hexdigest())
    value=base64.b64encode(data).decode()
    for i in range(0,len(value),400):print('GO_EVIDENCE_B64',value[i:i+400])
    print('GO_EVIDENCE_FILE_END',p.name)
