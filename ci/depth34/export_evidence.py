"""Export scoped test records only; never include environment variables or credentials."""
import base64,hashlib,json,pathlib
root=pathlib.Path('restored')
fp=json.loads(pathlib.Path('candidate/deliverables/CP11_DEPTH34_HOTEL_QUOTE_IDENTITY_20260910/SOURCE_FINGERPRINT.json').read_text())
for path,expected in fp.items():
    assert hashlib.sha256((root/path).read_bytes()).hexdigest()==expected,path
print('SOURCE_VERIFIED_AFTER_TESTS',len(fp))
for name in ['source-lineage.json','backend.xml','frontend.xml']:
    p=pathlib.Path('evidence')/name
    if not p.exists():
        print('GO_EVIDENCE_MISSING',name)
        continue
    data=p.read_bytes()
    print('GO_EVIDENCE_FILE_BEGIN',name,len(data),hashlib.sha256(data).hexdigest())
    encoded=base64.b64encode(data).decode()
    for offset in range(0,len(encoded),400):print('GO_EVIDENCE_B64',encoded[offset:offset+400])
    print('GO_EVIDENCE_FILE_END',name)
