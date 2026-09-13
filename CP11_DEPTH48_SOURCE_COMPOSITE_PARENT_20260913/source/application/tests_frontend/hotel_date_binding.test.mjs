import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const app=fs.readFileSync('frontend/consumer/app.js','utf8');
const source=app.slice(app.indexOf('function hotelOfferMatchesStay('),app.indexOf('function renderHotel('))+
  app.slice(app.indexOf('async function selectOffer('),app.indexOf('function renderReviewOrder('));
const stay={check_in:'2026-11-20',check_out:'2026-11-22'};
const offer=(id,extra={})=>({offer_id:id,...stay,currency:'CNY',...extra});
function setup(api) {
  const state={searchCriteria:{stay:{...stay},currency:'CNY'}};
  const calls=[],errors=[];
  const c={state,URLSearchParams,api,toast:e=>errors.push(e),renderHotel:()=>calls.push('hotel'),renderReviewOrder:()=>calls.push('review')};
  vm.createContext(c);vm.runInContext(source,c);return {c,state,calls,errors};
}

test('hotel detail requests the chosen stay and currency and excludes mixed historical quotes',async()=>{
  const fixture=setup(async url=>{
    const parsed=new URL(url,'https://example.test');
    assert.equal(parsed.pathname,'/v1/consumer/hotels/hotel_44');
    assert.equal(parsed.searchParams.get('check_in'),stay.check_in);
    assert.equal(parsed.searchParams.get('check_out'),stay.check_out);
    assert.equal(parsed.searchParams.get('currency'),'CNY');
    return {hotel_id:'hotel_44',offers:[offer('valid'),offer('old',{check_in:'2026-10-01'}),offer('usd',{currency:'USD'}),{offer_id:'missing-dates',currency:'CNY'}]};
  });
  await fixture.c.loadHotel('hotel_44');
  assert.deepEqual(Array.from(fixture.state.hotel.offers,x=>x.offer_id),['valid']);
  assert.deepEqual(fixture.calls,['hotel']);assert.deepEqual(fixture.errors,[]);
});

test('a stale selection cannot start prebooking for another date or currency',async()=>{
  const f=setup(()=>assert.fail('mismatched offer must never prebook'));
  for(const wrong of [offer('wrong',{check_out:'2026-11-23'}),offer('wrong',{currency:'USD'})]){
    f.state.hotel={offers:[wrong]};await f.c.selectOffer('wrong');
  }
  assert.equal(f.errors.length,2);assert.deepEqual(f.calls,[]);
});

test('the accepted same-stay offer supplies the prebooking currency and review data',async()=>{
  const f=setup(async(url,options)=>{
    assert.equal(url,'/v1/offers/correct/prebook');assert.equal(JSON.parse(options.body).currency,'CNY');
    return {prebook_id:'prebook_44',currency:'CNY'};
  });
  f.state.hotel={offers:[offer('correct')]};await f.c.selectOffer('correct');
  assert.equal(f.state.offer.check_in,stay.check_in);assert.equal(f.state.prebook.prebook_id,'prebook_44');
  assert.deepEqual(f.calls,['review']);
});

test('a late hotel response cannot overwrite the next search',async()=>{
  let finish;const f=setup(()=>new Promise(resolve=>{finish=resolve}));
  const pending=f.c.loadHotel('hotel_44');
  f.state.searchCriteria={stay:{check_in:'2026-12-01',check_out:'2026-12-03'},currency:'CNY'};
  finish({hotel_id:'hotel_44',offers:[offer('old')]});await pending;
  assert.equal(f.state.hotel,undefined);assert.deepEqual(f.calls,[]);
});

test('missing dates or a mismatched hotel response cannot show bookable offers',async()=>{
  const missing=setup(()=>assert.fail('date-less hotel quote request'));missing.state.searchCriteria=null;
  await missing.c.loadHotel('hotel_44');assert.equal(missing.errors.length,1);
  const wrong=setup(async()=>({hotel_id:'another_hotel',offers:[offer('wrong-hotel')]}));
  await wrong.c.loadHotel('hotel_44');assert.equal(wrong.errors.length,1);assert.equal(wrong.state.hotel,undefined);
});
