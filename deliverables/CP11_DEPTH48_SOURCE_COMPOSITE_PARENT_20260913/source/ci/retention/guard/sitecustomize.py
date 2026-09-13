"""Test-process egress guard. No external provider or remote database connections."""
import ipaddress
import socket
import sys

def guard(event,args):
    if event != 'socket.connect':
        return
    sock,address=args
    if sock.family == socket.AF_UNIX:
        return
    host=address[0]
    try:
        local=ipaddress.ip_address(host).is_loopback
    except ValueError:
        local=host == 'localhost'
    if not local:
        raise PermissionError('ISOLATED_TEST_EXTERNAL_EGRESS_FORBIDDEN')

sys.addaudithook(guard)
