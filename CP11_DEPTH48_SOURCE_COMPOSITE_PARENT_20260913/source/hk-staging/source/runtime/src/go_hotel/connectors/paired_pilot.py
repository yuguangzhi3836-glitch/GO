import hashlib
class SandboxHotelPilotAdapter:
 key='SANDBOX_HOTEL_PILOT_V1'
 def book(self,key,payload):return {'state':'CONFIRMED','reference':f'sbx_hotel_{hashlib.sha256(key.encode()).hexdigest()[:16]}'}
 def query(self,key,reference):return {'state':'CONFIRMED','reference':reference}
 def cancel(self,key,reference):return {'state':'CANCELLED','reference':reference}
class SandboxPspPilotAdapter:
 key='SANDBOX_PSP_PILOT_V1'
 def authorize(self,key,payload):return {'state':'AUTHORIZED','reference':f'sbx_pay_{hashlib.sha256(key.encode()).hexdigest()[:16]}'}
 def capture(self,key,reference):return {'state':'CAPTURED','reference':reference}
 def refund(self,key,reference):return {'state':'REFUNDED','reference':f'sbx_refund_{hashlib.sha256(key.encode()).hexdigest()[:16]}'}
 def settlement(self,key,reference):return {'state':'RECONCILED','reference':f'sbx_settle_{hashlib.sha256(key.encode()).hexdigest()[:16]}'}
