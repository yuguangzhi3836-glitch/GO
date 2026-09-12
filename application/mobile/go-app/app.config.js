const base=require('./app.json').expo;
const env=process.env.EXPO_PUBLIC_ENV||'development';
const apiByEnv={
  development:process.env.EXPO_PUBLIC_API_URL||'http://localhost:8000',
  staging:process.env.EXPO_PUBLIC_API_URL||'https://staging-api.go.travel',
  production:process.env.EXPO_PUBLIC_API_URL||'https://api.go.travel'
};
module.exports={expo:{...base,version:'1.1.0',runtimeVersion:{policy:'appVersion'},updates:{fallbackToCacheTimeout:0},extra:{...base.extra,environment:env,apiBaseUrl:apiByEnv[env],eas:{projectId:process.env.EXPO_PUBLIC_EAS_PROJECT_ID||'REPLACE_WITH_EAS_PROJECT_ID'}},ios:{...base.ios,buildNumber:process.env.IOS_BUILD_NUMBER||'1'},android:{...base.android,versionCode:Number(process.env.ANDROID_VERSION_CODE||1)}}};
