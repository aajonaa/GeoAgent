"""Encrypted account profiles; the key lives in persistent service state.

This protects a database-only copy and authenticated HTTP account boundaries.
It is NOT OS isolation from root or code running as the service account.
Back up the database and the protected key separately. Never log either.
"""
import json
import os
import stat
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ModelVaultError(ValueError):
    def __init__(self):
        super().__init__("Saved model configuration cannot be decrypted safely. Restore the protected server key, or clear the saved configuration and save it again.")


class ModelVault:
    def __init__(self, store):
        self.store = store
        self.key_directory = store.root / ".model-secrets"
        self.key_path = self.key_directory / "model-profiles.key"
        with store.lock, store.db:
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS model_profiles ("
                "uid TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,"
                "ciphertext BLOB NOT NULL, updated REAL NOT NULL)"
            )

    @staticmethod
    def _private(info, directory=False):
        if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                or (os.name == "posix" and
                    (info.st_uid != os.getuid() or info.st_mode & 0o077))):
            raise ModelVaultError()

    def _key(self, *, create=False):
        try:
            if create:
                self.key_directory.mkdir(mode=0o700, exist_ok=True)
            self._private(self.key_directory.lstat(), directory=True)
            if create and not self.key_path.exists() and not self.key_path.is_symlink():
                # Called under BEGIN IMMEDIATE, serializing first-key creation
                # across service processes. A lost key must never be replaced
                # while any encrypted account still depends on it.
                if self.store.db.execute("SELECT 1 FROM model_profiles LIMIT 1").fetchone():
                    raise ModelVaultError()
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as file:
                    file.write(AESGCM.generate_key(bit_length=256))
                    file.flush()
                    os.fsync(file.fileno())
            self._private(self.key_path.lstat())
            fd = os.open(self.key_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as file:
                self._private(os.fstat(file.fileno()))
                key = file.read(33)
            if len(key) != 32:
                raise ModelVaultError()
            return key
        except OSError:
            raise ModelVaultError() from None

    @staticmethod
    def _aad(uid):
        return ("geotoolagent:model-profile:v1:" + uid).encode("utf-8")

    def get(self, uid):
        with self.store.lock:
            row = self.store.db.execute(
                "SELECT ciphertext FROM model_profiles WHERE uid=?", (uid,)
            ).fetchone()
            if row is None:
                return None
            try:
                blob = bytes(row[0])
                if len(blob) < 29 or blob[:1] != b"\x01":
                    raise ModelVaultError()
                raw = AESGCM(self._key()).decrypt(blob[1:13], blob[13:], self._aad(uid))
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ModelVaultError()
                return result
            except (InvalidTag, ValueError, TypeError, UnicodeError):
                raise ModelVaultError() from None

    def put(self, uid, data):
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            key, nonce = self._key(create=True), os.urandom(12)
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            blob = b"\x01" + nonce + AESGCM(key).encrypt(nonce, raw, self._aad(uid))
            self.store.db.execute(
                "INSERT INTO model_profiles VALUES (?,?,?) ON CONFLICT(uid) "
                "DO UPDATE SET ciphertext=excluded.ciphertext,updated=excluded.updated",
                (uid, blob, time.time()),
            )

    def mutate(self, uid, change):
        """Atomically read/update one encrypted account collection.

        BEGIN IMMEDIATE also serializes independent server processes, so
        simultaneous additions cannot discard another connection.
        """
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            data = change(self.get(uid))
            if data is None:
                self.store.db.execute("DELETE FROM model_profiles WHERE uid=?", (uid,))
                return
            key, nonce = self._key(create=True), os.urandom(12)
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            blob = b"\x01" + nonce + AESGCM(key).encrypt(nonce, raw, self._aad(uid))
            self.store.db.execute(
                "INSERT INTO model_profiles VALUES (?,?,?) ON CONFLICT(uid) "
                "DO UPDATE SET ciphertext=excluded.ciphertext,updated=excluded.updated",
                (uid, blob, time.time()),
            )

    def delete(self, uid):
        # Deletion must remain possible even if the key was lost or tampered.
        with self.store.lock, self.store.db:
            self.store.db.execute("DELETE FROM model_profiles WHERE uid=?", (uid,))
