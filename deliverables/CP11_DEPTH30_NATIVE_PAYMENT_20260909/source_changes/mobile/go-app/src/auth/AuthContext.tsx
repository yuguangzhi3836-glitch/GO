import React,{createContext,useContext,useEffect,useState} from 'react';
import {api,login as apiLogin,logout as apiLogout,sessionVersion,onSessionChange} from '../api/client';
import {accessToken} from '../storage/secureSession';

type Auth={ready:boolean;authenticated:boolean;profile:any;login:(e:string,p:string)=>Promise<void>;logout:()=>Promise<void>;reload:()=>Promise<void>};
const C=createContext<Auth>(null as any);

export function AuthProvider({children}:{children:React.ReactNode}){
  const [ready,setReady]=useState(false);
  const [profile,setProfile]=useState<any>(null);
  const reload=async()=>{
    const version=sessionVersion();
    try{
      if(!await accessToken()){if(version===sessionVersion())setProfile(null);return;}
      const r=await api('/v1/consumer/me');if(version===sessionVersion())setProfile(r.data);
    }catch{if(version===sessionVersion())setProfile(null)}finally{setReady(true)}
  };
  useEffect(()=>{reload()},[]);
  useEffect(()=>onSessionChange(()=>setProfile(null)),[]);
  const login=async(e:string,p:string)=>{await apiLogin(e,p);await reload()};
  const logout=async()=>{try{await apiLogout()}catch{/* Local session clearing is guaranteed by the transport. */}};
  return <C.Provider value={{ready,authenticated:!!profile,profile,login,logout,reload}}>{children}</C.Provider>;
}
export const useAuth=()=>useContext(C);
