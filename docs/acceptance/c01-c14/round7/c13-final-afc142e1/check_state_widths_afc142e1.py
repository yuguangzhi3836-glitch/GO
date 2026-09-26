"""Conservative local AST scan; does not certify computed values/unmaterialized files."""
import ast,json
from pathlib import Path
root=Path('c13-round7/candidate-afc142e1/application/src/go_hotel')
models={}
for cls in ast.parse((root/'db/models.py').read_text()).body:
 if not isinstance(cls,ast.ClassDef):continue
 widths={}
 for node in cls.body:
  if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) and isinstance(node.value,ast.Call):
   for arg in node.value.args:
    if isinstance(arg,ast.Call) and isinstance(arg.func,ast.Name) and arg.func.id=='String' and arg.args and isinstance(arg.args[0],ast.Constant):widths[node.target.id]=arg.args[0].value
 models[cls.name]=widths

def strings(expr):return [n.value for n in ast.walk(expr) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
results=[];checks=0;files=0
for file in root.rglob('*.py'):
 if file.name=='models.py':continue
 t=ast.parse(file.read_text());aliases={}
 for node in ast.walk(t):
  if isinstance(node,ast.ImportFrom) and node.module=='go_hotel.db.models':
   for a in node.names:aliases[a.asname or a.name]=a.name
 def cls_of(n):
  if isinstance(n,ast.Name):return aliases.get(n.id)
  if isinstance(n,ast.Attribute) and n.attr in models:return n.attr
 def typed(expr):
  found={cls_of(n) for n in ast.walk(expr)}-{None}
  return next(iter(found)) if len(found)==1 else None
 def check(cls,col,val,line,kind):
  global checks
  size=models.get(cls,{}).get(col)
  if not size:return
  for v in strings(val):
   if not v or not all(c.isupper() or c.isdigit() or c in '_-' for c in v):continue
   checks+=1
   if len(v)>size:results.append({'file':str(file.relative_to(root)),'line':line,'model':cls,'column':col,'width':size,'literal':v,'length':len(v),'inference':kind})
 for node in ast.walk(t):
  if isinstance(node,ast.Call):
   cls=cls_of(node.func)
   if cls:
    for kw in node.keywords:
     if kw.arg:check(cls,kw.arg,kw.value,node.lineno,'constructor')
 for function in ast.walk(t):
  if not isinstance(function,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  local={}
  for n in ast.walk(function):
   if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call):
    inferred=typed(n.value)
    if inferred:
     for target in n.targets:
      if isinstance(target,ast.Name):local.setdefault(target.id,set()).add(inferred)
  for n in ast.walk(function):
   if isinstance(n,ast.Assign):
    for target in n.targets:
     if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name):
      classes=local.get(target.value.id,set())
      if len(classes)==1:check(next(iter(classes)),target.attr,n.value,n.lineno,'local-variable-inference')
 files+=1
out={'source_candidate':'afc142e16c050c0000da5a11a312620387be8f79','scope':'materialized local Python only; constructor and unambiguous local assignment uppercase literal static scan','python_files':files,'literal_column_checks':checks,'potential_width_violations':results,'not_covered':['computed/string-composed states','unmaterialized application files','true database schema drift','values from runtime input']}
Path('c13-round7/STATE_WIDTH_SCAN_afc142e1.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
