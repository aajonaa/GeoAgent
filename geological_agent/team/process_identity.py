"""Linux process identities. Numeric PIDs are observations, never signal authority."""
import os
from pathlib import Path
import select
import signal

from .recovery import RecoveryEvidenceError


def observe(pid):
    pid = int(pid)
    base = Path('/proc') / str(pid)
    parts = (base / 'stat').read_text().rsplit(') ', 1)[1].split()
    try:
        namespace = os.readlink(base / 'ns/pid')
    except FileNotFoundError:
        if parts[0] != 'Z':
            raise
        namespace = None
    return {'pid': pid, 'start_ticks': parts[19], 'state': parts[0],
            'ppid': int(parts[1]), 'pgid': int(parts[2]), 'sid': int(parts[3]),
            'uid': base.stat().st_uid, 'pid_namespace': namespace,
            'observer_pid_namespace': os.readlink('/proc/self/ns/pid'),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'cgroup': (base / 'cgroup').read_text().strip()}


def same(expected, actual):
    fields = ('pid', 'start_ticks', 'uid', 'boot_id')
    return (all(expected.get(k) == actual.get(k) for k in fields)
            and (actual.get('state') == 'Z' or expected.get('pid_namespace') == actual.get('pid_namespace')))


class ProcessHandle:
    """Reacquire around two identity reads, then signal only this pidfd."""
    def __init__(self, expected):
        if (not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal')
                or expected.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                or expected.get('observer_pid_namespace', expected.get('pid_namespace')) != os.readlink('/proc/self/ns/pid')):
            raise RecoveryEvidenceError('Process identity or pidfd unavailable')
        before = observe(expected['pid'])
        if not same(expected, before):
            raise RecoveryEvidenceError('Process identity changed before pidfd acquisition')
        self.expected = dict(expected)
        self.fd = os.pidfd_open(expected['pid'], 0)
        try:
            if not same(expected, observe(expected['pid'])):
                raise RecoveryEvidenceError('Process identity changed during pidfd acquisition')
            self.verify_fd()
        except BaseException:
            self.close()
            raise

    def verify_fd(self):
        fields = dict(line.split(':', 1) for line in Path('/proc/self/fdinfo/' + str(self.fd)).read_text().splitlines() if ':' in line)
        bound = int(fields['Pid'].strip())
        if bound != self.expected['pid'] and not (bound == -1 and self.exited()):
            raise RecoveryEvidenceError('pidfd refers to another process')

    def exited(self):
        poll = select.poll()
        poll.register(self.fd, select.POLLIN)
        return bool(poll.poll(0))

    def send(self, sig):
        self.verify_fd()
        if self.exited():
            return False
        try:
            actual = observe(self.expected['pid'])
        except FileNotFoundError:
            if self.exited():
                return False
            raise
        if not same(self.expected, actual):
            raise RecoveryEvidenceError('Refusing signal after process identity change')
        try:
            signal.pidfd_send_signal(self.fd, sig, None, 0)
        except ProcessLookupError:
            # The process may exit between the identity/poll check and the
            # syscall. Only this held pidfd's exit indication proves that race.
            if self.exited():
                return False
            raise
        return True

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
