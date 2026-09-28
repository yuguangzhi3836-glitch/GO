import fs from 'fs';
const files=['App.tsx','src/storage/secureSession.ts','src/api/client.ts','src/notifications/registerPush.ts','src/navigation/linking.ts'];
for(const f of files){if(!fs.existsSync(new URL('../'+f,import.meta.url))) throw new Error('missing '+f)}
const secure=fs.readFileSync(new URL('../src/storage/secureSession.ts',import.meta.url),'utf8');
if(!secure.includes('SecureStore')||secure.includes('localStorage'))throw new Error('secure storage contract failed');
const app=JSON.parse(fs.readFileSync(new URL('../app.json',import.meta.url),'utf8'));
if(app.expo.scheme!=='go')throw new Error('deep-link scheme missing');

const consumerScreens={
  flight:['src/screens/FlightTripDetailScreen.tsx',"当前未连接航空公司实时服务，请勿作为实际出行凭证。"],
  mobility:['src/screens/MobilityTripDetailScreen.tsx',"当前未连接真实车队，服务状态请以承运方确认为准。"],
  wallet:['src/screens/WalletScreen.tsx',"请通过合规支付渠道绑定；未连接支付渠道时无法添加支付方式。"],
  checkout:['src/screens/CheckoutScreen.tsx',"当前支付服务不可用于实际扣款，订单会保留。"],
  home:['src/screens/HomeScreen.tsx',"完成偏好或搜索后生成个性化推荐。"],
};
for(const [name,[file,truthfulState]] of Object.entries(consumerScreens)){
  const source=fs.readFileSync(new URL('../'+file,import.meta.url),'utf8');
  if(/模拟(?:体验|数据| Token)?/.test(source))throw new Error(name+' exposes simulation copy');
  if(!source.includes(truthfulState))throw new Error(name+' truthful unavailable-state copy missing');
}
for(const file of ['src/screens/FlightTripDetailScreen.tsx','src/screens/MobilityTripDetailScreen.tsx']){
  const source=fs.readFileSync(new URL('../'+file,import.meta.url),'utf8');
  if(!source.includes("data_mode==='SIMULATION'"))throw new Error(file+' lost internal mode boundary');
}
console.log('Sprint 1Z mobile contract: PASS');
console.log('C05 consumer Chinese/mobile copy governance: PASS (5 screens)');
