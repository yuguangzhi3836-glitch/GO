import * as SecureStore from 'expo-secure-store';
const ACCESS='go.mobile.access'; const REFRESH='go.mobile.refresh';
export async function saveTokens(accessToken:string,refreshToken:string){
  await SecureStore.setItemAsync(ACCESS,accessToken,{keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY});
  await SecureStore.setItemAsync(REFRESH,refreshToken,{keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY});
}
export async function accessToken(){ return SecureStore.getItemAsync(ACCESS); }
export async function refreshToken(){ return SecureStore.getItemAsync(REFRESH); }
export async function clearTokens(){ await Promise.all([SecureStore.deleteItemAsync(ACCESS),SecureStore.deleteItemAsync(REFRESH)]); }
