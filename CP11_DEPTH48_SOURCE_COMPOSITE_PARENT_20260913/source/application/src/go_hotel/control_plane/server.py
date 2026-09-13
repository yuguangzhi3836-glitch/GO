"""Local control bridge entry point; expose only through an approved TLS proxy."""
import argparse
import json
import os
from pathlib import Path

from .bridge import Store, create_app


def configured_app(config):
    nodes={}
    for node,profile in config['nodes'].items():
        nodes[node]={'token':os.environ[profile['token_env']],
                     'hmac_key':os.environ[profile['hmac_key_env']],
                     'targets':profile['targets']}
    return create_app(Store(config['ledger']),nodes,os.environ['GO_CP_OPERATOR_TOKEN'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--port',type=int,default=4180)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:
        app=configured_app(json.loads(args.config.read_text()))
    except (OSError,ValueError,TypeError,KeyError):
        print(json.dumps({'gate':'HOLD','reason':'CONTROL_CONFIGURATION_REQUIRED','executed':False}))
        return 2
    if args.check:
        print(json.dumps({'gate':'CONFIGURED_NOT_CONNECTED','executed':False}))
        return 0
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,proxy_headers=False,access_log=False)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
