import Constants from 'expo-constants';
import {accessToken,refreshToken,saveTokens,clearTokens} from '../storage/secureSession';
import {online,idempotencyKey} from './network';
import {createTransport} from './transport';
const API=String(Constants.expoConfig?.extra?.apiBaseUrl || 'http://localhost:8000').replace(/\/$/,'');
const transport=createTransport({baseUrl:API,fetch:(...args)=>fetch(...args),online,accessToken,refreshToken,saveTokens,clearTokens,newKey:()=>idempotencyKey('go')});
export const api=transport.request;
export const login=transport.login;
export const register=transport.register;
export const requestRegistrationCode=transport.requestRegistrationCode;
export const logout=transport.logout;
export const sessionVersion=transport.version;
export const onSessionChange=transport.subscribe;
export {API};

export type ConsumerRegistrationPolicy = {
  audience:string;
  status:string;
  acceptance_enabled:boolean;
  enabled:boolean;
  account_stage:boolean;
  versions:Record<string,string>;
  term_hashes:Record<string,string>;
  documents:Array<{id:string;title:string;version:string;status:string;sha256:string;content_url:string}>;
  deferred:string[];
  formal_approval_pending:boolean;
  unresolved:string[];
};

export async function getConsumerRegistrationPolicy():Promise<ConsumerRegistrationPolicy> {
  const result:any=await api('/v1/consumer/auth/registration');
  const data=result?.data;
  if(data?.audience!=='consumer' || !data?.versions || !data?.term_hashes || !Array.isArray(data?.documents))
    throw new Error('INVALID_REGISTRATION_POLICY');
  return data as ConsumerRegistrationPolicy;
}

export async function getRegistrationTermDocument(path:string) {
  if(!path.startsWith('/v1/registration-terms/'))throw new Error('INVALID_API_PATH');
  const result:any=await api(path);
  const data=result?.data;
  if(typeof data?.content!=='string')throw new Error('INVALID_REGISTRATION_TERM_DOCUMENT');
  return data as {id:string;title:string;version:string;status:string;content:string};
}
