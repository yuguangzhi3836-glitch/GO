#!/usr/bin/env python3
"""Join verified raw parts downloaded from this delivery folder."""
import argparse,hashlib,json
from pathlib import Path

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parts',type=Path,default=Path(__file__).resolve().parent/'parts');p.add_argument('--output-dir',type=Path,default=Path.cwd());a=p.parse_args()
 m=json.loads((a.parts/'PARTS.json').read_text())
 assert Path(m['filename']).name==m['filename']
 output=a.output_dir/m['filename'];a.output_dir.mkdir(parents=True,exist_ok=True)
 if output.exists():
  assert output.stat().st_size==m['size'] and sha(output)==m['sha256'],'Existing output differs; choose another output directory'
  print(output);return
 stage=output.with_suffix(output.suffix+'.assembling')
 created=False
 try:
  with stage.open('xb') as f:
   created=True
   for part in m['parts']:
    assert Path(part['filename']).name==part['filename']
    q=a.parts/part['filename'];assert q.stat().st_size==part['size'] and sha(q)==part['sha256'],q.name
    with q.open('rb') as source:
     for block in iter(lambda:source.read(1048576),b''):f.write(block)
  assert stage.stat().st_size==m['size'] and sha(stage)==m['sha256'],'Joined archive mismatch'
  output.hardlink_to(stage)
  stage.unlink()
 except BaseException:
  # Remove only the staging file created by this invocation.
  if created and stage.exists():stage.unlink()
  raise
 print(output)
if __name__=='__main__':main()
