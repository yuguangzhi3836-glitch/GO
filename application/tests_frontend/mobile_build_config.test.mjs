import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const configure=createRequire(import.meta.url)('../mobile/go-app/app.config.js');
function build(env){
  const names=['EAS_BUILD_PROFILE','EXPO_PUBLIC_ENV','EXPO_PUBLIC_API_BASE_URL','EXPO_PUBLIC_API_URL','EXPO_PUBLIC_EAS_PROJECT_ID','IOS_BUILD_NUMBER','ANDROID_VERSION_CODE'];
  const old=Object.fromEntries(names.map(n=>[n,process.env[n]]));
  try{
    for(const n of names){if(env[n]===undefined)delete process.env[n];else process.env[n]=env[n];}
    return configure({config:{name:'GO',extra:{apiBaseUrl:'http://localhost:8000',retained:true}}});
  }finally{for(const n of names){if(old[n]===undefined)delete process.env[n];else process.env[n]=old[n];}}
}
test('local build preserves development API and unrelated Expo config',()=>{
  const c=build({});assert.equal(c.extra.apiBaseUrl,'http://localhost:8000');assert.equal(c.name,'GO');assert.equal(c.extra.retained,true);
});
test('preview and production require an explicit API binding',()=>{
  for(const profile of ['preview','production'])assert.throws(()=>build({EAS_BUILD_PROFILE:profile}),/GO_BUILD_API_BASE_URL_REQUIRED/);
  assert.throws(()=>build({EXPO_PUBLIC_ENV:'staging'}),/GO_BUILD_API_BASE_URL_REQUIRED/);
});
test('external builds reject loopback, placeholder, plaintext and credential URLs',()=>{
  for(const url of ['http://api.example.test','https://localhost','https://127.0.0.1','https://[::1]','https://0.0.0.0','https://isolated.invalid','https://name:password@api.example.test','https://api.example.test?token=x'])
    assert.throws(()=>build({EAS_BUILD_PROFILE:'preview',EXPO_PUBLIC_API_BASE_URL:url}));
});
test('explicit HTTPS build API reaches the same extra field consumed by client.ts',()=>{
  const c=build({EAS_BUILD_PROFILE:'preview',EXPO_PUBLIC_API_BASE_URL:'https://api.example.test/'});
  assert.equal(c.extra.apiBaseUrl,'https://api.example.test');
});
test('existing environment names and release metadata remain compatible',()=>{
  const c=build({EXPO_PUBLIC_ENV:'staging',EXPO_PUBLIC_API_URL:'https://api.example.test',
    EXPO_PUBLIC_EAS_PROJECT_ID:'fixture-project',IOS_BUILD_NUMBER:'17',ANDROID_VERSION_CODE:'23'});
  assert.equal(c.extra.apiBaseUrl,'https://api.example.test');assert.equal(c.extra.environment,'staging');
  assert.equal(c.extra.eas.projectId,'fixture-project');assert.equal(c.version,'1.1.0');
  assert.deepEqual(c.runtimeVersion,{policy:'appVersion'});assert.equal(c.updates.fallbackToCacheTimeout,0);
  assert.equal(c.ios.buildNumber,'17');assert.equal(c.android.versionCode,23);
});
