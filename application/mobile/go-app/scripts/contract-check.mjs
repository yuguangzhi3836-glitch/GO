import fs from 'fs';
const files=['App.tsx','src/storage/secureSession.ts','src/api/client.ts','src/notifications/registerPush.ts','src/navigation/linking.ts'];
for(const f of files){if(!fs.existsSync(new URL('../'+f,import.meta.url))) throw new Error('missing '+f)}
const secure=fs.readFileSync(new URL('../src/storage/secureSession.ts',import.meta.url),'utf8');
if(!secure.includes('SecureStore')||secure.includes('localStorage'))throw new Error('secure storage contract failed');
const app=JSON.parse(fs.readFileSync(new URL('../app.json',import.meta.url),'utf8'));
if(app.expo.scheme!=='go')throw new Error('deep-link scheme missing');
console.log('Sprint 1Z mobile contract: PASS');
