from go_hotel.services.browser_network_inventory_discovery import browser_network_inventory_discovery
from go_hotel.services.chain_hotel_registry import ChainCode
import json

def entry(url,payload):return {"_resourceType":"xhr","request":{"url":url},"response":{"status":200,"content":{"mimeType":"application/json","text":json.dumps(payload)}}}
def capture(chain_host,ids):
 entries=[]
 for page,chunk in enumerate((ids[:2],ids[2:]),1):
  hotels=[{"hotelId":x,"hotelName":f"Hotel {x}","hotelUrl":f"https://{chain_host}/hotel/{x}"} for x in chunk]
  entries.append(entry(f"https://{chain_host}/api/hotels?page={page}",{"hotels":hotels,"total":len(ids),"nextPage":page+1 if page==1 else None}))
 return {"log":{"entries":entries}}

def test_stable_two_capture_pagination_can_pass():
 cap=capture("www.hworld.com",["1","2","3"])
 result=browser_network_inventory_discovery.compare_independent_captures(chain=ChainCode.H_WORLD,captures=[cap,cap])
 assert result["status"]=="PASS" and result["stable_inventory_sha"] is True

def test_inventory_drift_holds():
 a=capture("www.hworld.com",["1","2","3"]);b=capture("www.hworld.com",["1","2","4"])
 result=browser_network_inventory_discovery.compare_independent_captures(chain=ChainCode.H_WORLD,captures=[a,b])
 assert result["status"]=="HOLD"

def test_third_party_hotel_url_is_not_inventory_truth():
 cap={"log":{"entries":[entry("https://www.hworld.com/api/hotels?page=1",{"hotels":[{"hotelId":"1","hotelName":"Bad","hotelUrl":"https://example.com/hotel/1"}],"total":1,"nextPage":None})]}}
 result=browser_network_inventory_discovery.analyze_capture(chain=ChainCode.H_WORLD,capture=cap)
 assert result["property_count"]==0 and result["pagination_contract_proven"] is False

def test_atour_wrong_domain_capture_is_rejected():
 cap=capture("www.atour.com",["1","2","3"])
 result=browser_network_inventory_discovery.analyze_capture(chain=ChainCode.ATOUR,capture=cap)
 assert result["property_count"]==0
