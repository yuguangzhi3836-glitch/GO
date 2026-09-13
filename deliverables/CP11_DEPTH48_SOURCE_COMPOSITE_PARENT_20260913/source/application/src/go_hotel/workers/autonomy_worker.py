"""Run with python -m go_hotel.workers.autonomy_worker [--once].

Run explicitly after migration; not automatically enabled by API startup.
No shell adapter, arbitrary import, provider dispatch or schema creation exists.
"""
import argparse
import json
import logging
import os
import signal
import threading
import uuid

from sqlalchemy.exc import OperationalError
from go_hotel.autonomy.durable import ExecutionError
from go_hotel.autonomy.operations import application_executor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--cell', choices=['C%02d' % n for n in range(1, 15)])
    parser.add_argument('--poll-seconds', type=float, default=1)
    args = parser.parse_args(argv)
    if not 0.1 <= args.poll_seconds <= 30:
        parser.error('poll-seconds must be between 0.1 and 30')
    runtime = application_executor()
    worker = 'autonomy-%s-%s' % (os.getpid(), uuid.uuid4().hex[:12])
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            result = runtime.run_once(worker, cell_id=args.cell)
        except (OperationalError, ExecutionError) as exc:
            # Errors must remain visible without logging DB URLs or payloads.
            logging.getLogger('go.autonomy').error('WORKER_ERROR:%s', type(exc).__name__)
            if args.once:
                return 1
            stop.wait(args.poll_seconds)
            continue
        if result:
            print(json.dumps({k: result[k] for k in ('task_id', 'cell_id', 'status', 'attempt', 'last_code')}), flush=True)
        if args.once:
            return 0
        if result is None:
            stop.wait(args.poll_seconds)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
