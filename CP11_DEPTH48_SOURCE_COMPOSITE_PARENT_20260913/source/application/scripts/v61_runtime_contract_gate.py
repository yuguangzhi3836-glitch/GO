import asyncio
from httpx import ASGITransport, AsyncClient
from go_hotel.main import app

async def run():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get('/v1/ai-infrastructure/manifest')
        assert r.status_code == 200
        j = r.json()
        assert 'AI_AGENT' in j['clients']
        assert j['base_call_price_cny'] == 0
        assert j['paid_recommendation_ranking'] is False
        assert 'DOES_NOT_BUY_DISTRIBUTION' in j['distribution_principle']
    print('V61_RUNTIME_CONTRACT_OK')

if __name__ == '__main__':
    asyncio.run(run())
