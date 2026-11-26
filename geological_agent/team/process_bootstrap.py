"""Trusted pre-payload gate. Standalone stdlib only; no Agent imports here."""
import json
import os
import socket
import sys


def main():
    fd, execution, nonce = sys.argv[1:]
    channel = socket.socket(fileno=int(fd))
    channel.settimeout(5)
    channel.sendall((json.dumps({'ready': execution, 'nonce': nonce}) + '\n').encode())
    raw = bytearray()
    while not raw.endswith(b'\n'):
        part = channel.recv(4096)
        if not part:
            return  # Broker died or denied authorization. Never execute the payload.
        raw.extend(part)
        if len(raw) > 1024 * 1024:
            raise ValueError('Bootstrap gate packet exceeds quota')
    packet = json.loads(raw)
    if packet.get('go') != execution or packet.get('nonce') != nonce:
        raise ValueError('Bootstrap execution authorization mismatch')
    command, environment = packet['argv'], packet['env']
    if not isinstance(command, list) or not command or not isinstance(environment, dict):
        raise ValueError('Invalid trusted launch configuration')
    channel.close()
    os.execve(command[0], command, environment)


if __name__ == '__main__':
    main()
