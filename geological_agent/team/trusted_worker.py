"""Reuses the native Trusted runtime after the ownership gate; no manager key."""
import os
import signal
import sys
from threading import Event

from . import worker
from .protocol import decode, file_packet, unpack_files


def main():
    worker.OUTPUT = os.fdopen(os.dup(1), 'wb', buffering=0)
    sys.stdout = sys.stderr
    initial = worker.receive()
    cancel = Event()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    from .trusted import TrustedLocalRunner
    runner = TrustedLocalRunner(initial['jobs_root'])
    broker = worker.BrokerModel()
    try:
        result = runner._run_local(initial['rid'], initial['query'], unpack_files(initial['files']),
            cancel, lambda request, event: broker.invoke(request),
            lambda kind, fields: worker.send({'kind': 'trace', 'event': kind, 'fields': worker.encode(fields)}),
            settings=initial.get('settings'), **decode(initial.get('options', {})))
        files = result.pop('files')
        worker.send({'kind': 'done', 'result': result, 'files': [file_packet(k, v) for k, v in files.items()]})
    except Exception as exc:
        worker.send({'kind': 'failure', 'message': type(exc).__name__ + ': ' + str(exc)})
        raise SystemExit(1)


if __name__ == '__main__':
    main()
