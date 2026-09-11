import * as Notifications from 'expo-notifications';
import * as Linking from 'expo-linking';

export function installPushLifecycle(){
  const foreground=Notifications.addNotificationReceivedListener(()=>{});
  const response=Notifications.addNotificationResponseReceivedListener(r=>{
    const url=(r.notification.request.content.data as any)?.deep_link;
    if(typeof url==='string') Linking.openURL(url);
  });
  return()=>{foreground.remove();response.remove()};
}
