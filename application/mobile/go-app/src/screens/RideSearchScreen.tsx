import React from 'react';
import MobilitySearchForm from '../components/MobilitySearchForm';
import {api} from '../api/client';

export default function RideSearchScreen({navigation}:any) {
  return <MobilitySearchForm kind="ride" onSearch={async search=>{
    const response=await api('/v1/mobility/rides/search',{method:'POST',body:JSON.stringify(search)});
    navigation.navigate('RideResults',{items:response.data?.items||[],search});
  }}/>;
}
