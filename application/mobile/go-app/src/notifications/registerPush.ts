import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import * as Application from 'expo-application';
import {Platform} from 'react-native';
import {api} from '../api/client';
Notifications.setNotificationHandler({handleNotification:async()=>({shouldShowBanner:true,shouldShowList:true,shouldPlaySound:false,shouldSetBadge:false})});
export async function registerPush(){
  if(!Device.isDevice) return {registered:false,reason:'PHYSICAL_DEVICE_REQUIRED'};
  const current=await Notifications.getPermissionsAsync(); let status=current.status;
  if(status!=='granted') status=(await Notifications.requestPermissionsAsync()).status;
  const deviceId=(await Application.getInstallationTimeAsync()).getTime().toString()+':'+(Application.applicationId||'go');
  let pushToken:string|undefined; if(status==='granted') pushToken=(await Notifications.getDevicePushTokenAsync()).data as string;
  return api('/v1/mobile/devices',{method:'POST',body:JSON.stringify({device_id:deviceId,platform:Platform.OS==='ios'?'IOS':'ANDROID',app_version:Application.nativeApplicationVersion||undefined,device_model:Device.modelName||undefined,os_version:Device.osVersion||undefined,push_provider:Platform.OS==='ios'?'APNS':'FCM',push_token:pushToken,notifications_enabled:status==='granted'})});
}
