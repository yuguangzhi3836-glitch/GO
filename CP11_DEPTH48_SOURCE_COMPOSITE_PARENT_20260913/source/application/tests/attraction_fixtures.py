"""Explicit valid setup for historical positive attraction scenarios."""
def quoted_attraction(client, body, headers=None):
    body=dict(body)
    quantity=body.get('quantity',1)
    quote={k:body[k] for k in ('offer_id','visit_date','session_time','quantity','currency') if k in body}
    response=client.post('/v1/attractions/prebook',json=quote,headers=headers or {})
    assert response.status_code==200,response.text
    q=response.json()['data']
    body.update(prebook_id=q['prebook_id'],session_time=q['session_time'])
    if not body.get('traveler_ids') and not body.get('attendees'):
        body['attendees']=[{'full_name':f'ISOLATED ADULT {i+1}'} for i in range(quantity)]
    return body
