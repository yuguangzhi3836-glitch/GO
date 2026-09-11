import NetInfo from '@react-native-community/netinfo';
import AsyncStorage from '@react-native-async-storage/async-storage';

const QUEUE_KEY='go.nonsecret.retry.queue.v1';
export type RetryItem={id:string;path:string;method:string;body?:string;createdAt:number};
export async function online(){const n=await NetInfo.fetch();return !!n.isConnected && n.isInternetReachable!==false}
export async function enqueueRetry(item:RetryItem){const q=await loadQueue();if(!q.find(x=>x.id===item.id)){q.push(item);await AsyncStorage.setItem(QUEUE_KEY,JSON.stringify(q.slice(-50)))}}
export async function loadQueue():Promise<RetryItem[]>{try{return JSON.parse(await AsyncStorage.getItem(QUEUE_KEY)||'[]')}catch{return []}}
export async function removeRetry(id:string){const q=(await loadQueue()).filter(x=>x.id!==id);await AsyncStorage.setItem(QUEUE_KEY,JSON.stringify(q))}
export async function clearRetryQueue(){await AsyncStorage.removeItem(QUEUE_KEY)}
export function idempotencyKey(prefix='mob'){return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2)}`}
