"""Derive readable acceptance state only from recorded results bound to this source."""
import json
from pathlib import Path
r=Path(__file__).resolve().parent;o=r/'evidence-publication/deliverables/CP11_DEPTH37_ACCEPTANCE_20260910'
o.mkdir(parents=True,exist_ok=True);state=json.loads((r/'NEXT_STATE.json').read_text())
def load(directory,name):
 p=r/directory/name
 return json.loads(p.read_text()) if p.exists() else None
def accepted(directory,names):
 binding=load(directory,'source-binding.json');after=load(directory,'source-after-build.json');commands=load(directory,'commands.json')
 if not binding or not commands:return 'PENDING'
 if binding['candidate']!=state['candidate_commit'] or binding['source_tree_sha256']!=state['source_tree_sha256']:return 'FAIL_SOURCE_BINDING'
 checks={x['name']:x for x in commands}
 if any(n not in checks for n in names):return 'NOT_COMPLETED'
 if not all(checks[n]['pass'] for n in names):return 'FAIL'
 if not after or after.get('source_after_build')!='PASS':return 'FAIL_SOURCE_AFTER'
 return 'PASS'
android='final-android-evidence';ios='final-ios-evidence';smoke='android-startup-evidence'
gates={
 'node_seal':accepted(android,['node-provision','node-integrity','node-offline-replay','node-reject-tampering','node-reject-host-precedence','node-replay-restored']),
 'frontend_regression':accepted(android,['frontend-tests']),
 'provider_contracts_and_input_tests':accepted(android,['provider-contract','provider-input-tests','provider-input-preflight']),
 'android_release_x86_64_build':accepted(android,['mobile-install','native-module-discovery','mobile-typecheck','mobile-contract','mobile-export','native-prebuild','native-directory-module-discovery','android-bundled-build']),
 'ios_simulator_build_and_login':accepted(ios,['mobile-install','native-module-discovery','mobile-typecheck','mobile-contract','mobile-export','native-prebuild','native-directory-module-discovery','ios-pods','ios-simulator-build','ios-simulator-install','ios-login-screen','ios-no-fatal-startup']),
 'android_emulator_login':'PENDING',
 'physical_devices':'NOT_RUN_MISSING_DEVICE_ENVIRONMENT',
 'provider_external_certification':'NOT_RUN_MISSING_SANDBOX_INPUTS',
 'three_role_real_browser':'DEFERRED_POST_DEPLOYMENT',
 'six_category_real_e2e':'DEFERRED_POST_DEPLOYMENT',
 'postgres_real_integration':'NOT_RUN_PARENT_SIX_TESTS_SKIPPED',
 'final_release':'HOLD'}
pg=load('postgres-evidence','postgres-result.json')
if pg:
 gates['postgres_real_integration']=accepted('postgres-evidence',['postgres-migrate','postgres-race-tests']) if pg.get('pass')==6 and pg.get('skip')==0 else 'FAIL'
s=load(smoke,'startup-result.json');binding=load(smoke,'artifact-binding.json')
if s and binding:
 gates['android_emulator_login']='PASS' if s.get('login_rendered') and not s.get('fatal_startup') and binding.get('candidate')==state['candidate_commit'] and binding.get('source_tree_sha256')==state['source_tree_sha256'] else 'FAIL'
status={'candidate':state['candidate_commit'],'source_tree_sha256':state['source_tree_sha256'],'source_files':state['verified_files'],'build_run':state['run'],'build_ci_commit':state['ci_commit'],'android_startup_run':state.get('android_startup_run'),'postgres_run':state.get('postgres_run'),'provider_input_run':state.get('provider_preflight_run'),'gates':gates,'parent_backend_acceptance':{'candidate':state['parent_candidate'],'run':34453179558,'tests_total':1679,'pass':1673,'skip':6,'fail':0,'rerun_in_this_scope':False},'new_test_scope':{'frontend':244,'provider_contracts':27,'provider_input_tests':5},'deployed':False,'merged':False,'commercial_completion':False}
(o/'STATUS.json').write_text(json.dumps(status,indent=2,ensure_ascii=False)+'\n')
labels={'node_seal':'Node 密封、离线还原、防篡改','frontend_regression':'前端回归（244 项）','provider_contracts_and_input_tests':'供应商适配合约（27 项）与输入校验（5 项）','android_release_x86_64_build':'Android Release x86_64 构建','ios_simulator_build_and_login':'iOS 模拟器构建与登录页启动','android_emulator_login':'Android 模拟器登录页启动','physical_devices':'Android / iOS 真机','provider_external_certification':'供应商真实认证','three_role_real_browser':'消费者、供应商、管理员真实浏览器操作','six_category_real_e2e':'六品类真实操作闭环','postgres_real_integration':'真实 PostgreSQL 集成','final_release':'正式放行'}
rows='\n'.join('| '+labels[k]+' | '+v+' |' for k,v in gates.items())
text=f'''# DEPTH37R2 部署前验收记录

当前源码候选：`{state['candidate_commit']}`；源码指纹：`{state['source_tree_sha256']}`；共 {state['verified_files']} 个文件。

本次修复 Expo 原生模块缺失造成的白屏。四个既有版本的 Expo 运行时模块已改为应用直接依赖，锁文件由隔离 npm 生成；移除了随工作目录变化而失效的自定义搜索路径。验收同时检查应用目录和生成的原生目录，启动验证保存实际界面与错误日志。

| 验收项 | 状态 |
| --- | --- |
{rows}

父版本完整验收为 1,673 项通过、6 项 PostgreSQL 测试跳过、0 项失败；本次保留该历史结果，并另用一次性 PostgreSQL 实例补验这六项，独立结果见上表；没有重复执行完整后端测试。本次新增范围的结果见 STATUS.json 和原始命令记录。

Android 产物为 CI 内部签名的 x86_64 Release APK；iOS 产物用于模拟器。模拟器启动通过不代表真机权限、深链、通知和部署后网络会话均已验收，也不代表应用商店发布包可用。

供应商输入校验只证明防止缺参或不合规输入进入现有认证流程；真实认证仍须供应商认可的沙箱账号、测试库存和外部回执。所需输入及关闭条件见 REMAINING_EXTERNAL_INPUTS.md。

三角色真实浏览器操作与六品类真实闭环，按用户决定放在部署后验证；未将它们标为通过。香港负责已批准产物的服务器部署，开发和修复由 GO Command Center 负责。本记录未执行合并、部署或真实交易。

构建运行：https://github.com/yuguangzhi3836-glitch/GO/actions/runs/{state['run']}

Android 启动运行：https://github.com/yuguangzhi3836-glitch/GO/actions/runs/{state.get('android_startup_run')}

ACCEPTANCE_RUNS.json 保留全部已采集尝试，包括原始白屏、检查器输出格式错误、陈旧 PR 基线拒绝以及原生目录链接失败。原始日志位于 RAW_EVIDENCE.tar.gz，逐文件指纹见 RAW_EVIDENCE_INVENTORY.json。历史“构建成功”不能覆盖实际启动失败。
'''
(o/'README.md').write_text(text);print(json.dumps(gates,indent=2))
