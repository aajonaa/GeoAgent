"""Exclusive candidate cgroups addressed through verified directory descriptors."""
import os
from pathlib import Path
import re
import stat

from .recovery import RecoveryEvidenceError

DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def directory_identity(fd):
    value = os.fstat(fd)
    return {'device': value.st_dev, 'inode': value.st_ino}


def read_at(fd, name):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    try:
        raw = os.read(handle, 1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise RecoveryEvidenceError('Cgroup observation exceeds bounded quota')
        return raw.decode()
    finally:
        os.close(handle)


def write_at(fd, name, value):
    handle = os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    try:
        raw = value.encode()
        if os.write(handle, raw) != len(raw):
            raise OSError('Incomplete cgroup operation')
    finally:
        os.close(handle)


class CgroupRoot:
    def __init__(self, path):
        path = Path(path)
        if (not path.is_absolute() or '..' in path.parts or path.is_symlink()
                or path.resolve() != path
                or not str(path).startswith('/sys/fs/cgroup/user.slice/user-' + str(os.getuid()) + '.slice/user@' + str(os.getuid()) + '.service/')
                or not re.fullmatch(r'oresage-p31b4b2b(?:1|2a|2b1)-[a-f0-9]{32}\.service', path.name)):
            raise RecoveryEvidenceError('Only an exclusive candidate unit may delegate processes')
        mounts = [line.split(' - ', 1) for line in Path('/proc/self/mountinfo').read_text().splitlines()]
        if not any(part[1].split()[0] == 'cgroup2' and path.is_relative_to(Path(part[0].split()[4])) for part in mounts):
            raise RecoveryEvidenceError('Candidate requires cgroup v2')
        self.path = path
        self.fd = os.open(path, DIRECTORY)
        self.identity = {'path': str(path), **directory_identity(self.fd),
                         'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                         'cgroup_namespace': os.readlink('/proc/self/ns/cgroup')}
        if os.fstat(self.fd).st_uid != os.getuid() or os.getpid() not in self.members():
            self.close()
            raise RecoveryEvidenceError('Broker is not in its own delegated candidate root')

    def verify(self, expected=None):
        if expected is not None and expected != self.identity:
            raise RecoveryEvidenceError('Cgroup root generation mismatch')
        fd = os.open(self.path, DIRECTORY)
        try:
            if directory_identity(fd) != {k: self.identity[k] for k in ('device', 'inode')}:
                raise RecoveryEvidenceError('Delegation directory replaced')
        finally:
            os.close(fd)

    def members(self):
        return [int(v) for v in read_at(self.fd, 'cgroup.procs').split()]

    def create(self, execution_id):
        if not re.fullmatch('[a-f0-9]{32}', execution_id):
            raise RecoveryEvidenceError('Invalid execution identity')
        self.verify()
        name = 'exec-' + execution_id
        os.mkdir(name, mode=0o700, dir_fd=self.fd)
        with self.open(execution_id) as group:
            return group.identity

    def open(self, execution_id, expected=None):
        self.verify()
        if not re.fullmatch('[a-f0-9]{32}', execution_id):
            raise RecoveryEvidenceError('Invalid cgroup leaf identity')
        return ExecutionGroup(self, execution_id, expected)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class ExecutionGroup:
    def __init__(self, root, execution_id, expected):
        self.root, self.name = root, 'exec-' + execution_id
        self.fd = os.open(self.name, DIRECTORY, dir_fd=root.fd)
        self.identity = {'path': str(root.path / self.name), **directory_identity(self.fd), 'root': root.identity}
        if expected is not None and self.identity != expected:
            self.__exit__()
            raise RecoveryEvidenceError('Execution cgroup identity mismatch')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def verify(self):
        self.root.verify(self.identity['root'])
        fd = os.open(self.name, DIRECTORY, dir_fd=self.root.fd)
        try:
            if directory_identity(fd) != {k: self.identity[k] for k in ('device', 'inode')}:
                raise RecoveryEvidenceError('Execution cgroup replaced')
        finally:
            os.close(fd)

    def snapshot(self):
        self.verify()
        rows = []
        def visit(fd, relative):
            if len(rows) >= 256:
                raise RecoveryEvidenceError('Cgroup descendant observation quota exceeded')
            events = dict(line.split() for line in read_at(fd, 'cgroup.events').splitlines())
            if events.get('populated') not in ('0', '1'):
                raise RecoveryEvidenceError('Missing authoritative populated observation')
            rows.append({'relative': relative, **directory_identity(fd), 'populated': int(events['populated']),
                         'pids': [int(v) for v in read_at(fd, 'cgroup.procs').split()]})
            for name in os.listdir(fd):
                if stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                    child = os.open(name, DIRECTORY, dir_fd=fd)
                    try:
                        visit(child, relative + '/' + name)
                    finally:
                        os.close(child)
        visit(self.fd, '.')
        return {'groups': rows, 'empty': all(not r['pids'] and r['populated'] == 0 for r in rows),
                'pids': sorted({pid for r in rows for pid in r['pids']})}

    def attach(self, handle):
        self.verify()
        handle.verify_fd()
        if handle.exited():
            raise RecoveryEvidenceError('Bootstrap exited before cgroup attachment')
        write_at(self.fd, 'cgroup.procs', str(handle.expected['pid']))
        self.require_member(handle.expected['pid'])

    def require_member(self, pid):
        if pid not in self.snapshot()['pids']:
            raise RecoveryEvidenceError('Process is outside its execution cgroup')
        location = (Path('/proc') / str(pid) / 'cgroup').read_text().strip()
        if not location.startswith('0::') or self.name not in Path(location[3:]).parts:
            raise RecoveryEvidenceError('Process membership and cgroup observation disagree')

    def kill(self):
        self.verify()
        write_at(self.fd, 'cgroup.kill', '1')

    def remove(self):
        if not self.snapshot()['empty']:
            raise RecoveryEvidenceError('Cannot remove populated execution cgroup')
        if len(self.snapshot()['groups']) != 1:
            raise RecoveryEvidenceError('Cannot remove execution cgroup with child groups')
        self.verify()
        os.rmdir(self.name, dir_fd=self.root.fd)
