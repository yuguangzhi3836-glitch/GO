import React from 'react';
import MobilitySearchForm from '../components/MobilitySearchForm';
import {api} from '../api/client';

export default function RentalSearchScreen({navigation}:any) {
  return <MobilitySearchForm kind="rental" onSearch={async search=>{
    const response=await api('/v1/mobility/rentals/search',{method:'POST',body:JSON.stringify(search)});
    navigation.navigate('RentalResults',{items:response.data?.items||[],search});
  }}/>;
}
