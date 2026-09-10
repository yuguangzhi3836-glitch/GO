import json,os,time,urllib.request
url='https://api.github.com/repos/yuguangzhi3836-glitch/GO/actions/runs/34476573746'
for attempt in range(180):
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=30) as response:data=json.load(response)
    assert data['head_sha']=='43b331460e6ebee6fb5916ffd29cd2a0bbfab204','BUILD_COMMIT_MISMATCH'
    if data['status']=='completed':
        assert data['conclusion']=='success','UPSTREAM_BUILD_NOT_ACCEPTED'
        print('EXACT_BUILD_COMPLETED');break
    if attempt%6==0:print('Waiting for fixed build run 34476573746',flush=True)
    time.sleep(10)
else:raise RuntimeError('UPSTREAM_BUILD_TIMEOUT')
