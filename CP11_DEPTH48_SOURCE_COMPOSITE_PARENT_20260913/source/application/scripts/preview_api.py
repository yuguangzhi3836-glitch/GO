"""Isolated visual review bootstrap, never a production database initializer."""
import os
from pathlib import Path

root=Path(__file__).resolve().parents[1]
expected='sqlite+pysqlite:///'+str(root/'.preview/review.db')
if os.environ.get('GO_PREVIEW_ONLY')!='1' or os.environ.get('DATABASE_URL')!=expected:
    raise SystemExit('PREVIEW_ISOLATION_REQUIRED')

from go_hotel.db.models import Base
from go_hotel.db.session import engine
Base.metadata.create_all(engine)
from go_hotel.main import app
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=4174,access_log=False)
