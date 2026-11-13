"""RAM by default, with explicit opt-in bounded SD training memory."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import threading
import time

OFFSET = 52428800
HEADER_BYTES = 4096
SLOT_BYTES = 262144
REGION_BYTES = HEADER_BYTES + 2 * SLOT_BYTES
MAGIC = b'VPTRAIN1'
# Filled from the pinned upstream image by the build tooling; no device is read.
MBR_SHA256 = 'f1ccd797507975c40232f89f4df032845d1910c430f20c4245041f062aca943d'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def header(mbr):
    digest = hashlib.sha256(mbr).digest()
    if len(mbr) != 512 or digest.hex() != MBR_SHA256:
        raise ValueError('Training journal requires the pinned boot layout')
    data = struct.pack('<8s4I32s', MAGIC, 1, HEADER_BYTES, SLOT_BYTES, 2, digest)
    return data.ljust(HEADER_BYTES, b'\0')


def pack_slot(generation, payload):
    body = {'generation': generation, 'payload': payload, 'schema': 1}
    record = canonical({'body': body, 'sha256': hashlib.sha256(canonical(body)).hexdigest()})
    if len(record) + 1 > SLOT_BYTES:
        raise ValueError('Training history exceeds its bounded save slot')
    return (record + b'\n').ljust(SLOT_BYTES, b' ')


def unpack_slot(data):
    if len(data) != SLOT_BYTES:
        return None
    try:
        record = json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        body = record['body']
        if (set(record) != {'body', 'sha256'} or set(body) != {'schema', 'generation', 'payload'}
                or body['schema'] != 1 or type(body['generation']) is not int
                or not 0 <= body['generation'] < 2**63 or not isinstance(body['payload'], dict)
                or hashlib.sha256(canonical(body)).hexdigest() != record['sha256']):
            return None
        return body
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None


def initial_region(mbr):
    return header(mbr) + pack_slot(0, {}) + pack_slot(0, {})


def hardware_journal():
    # Kernel/MMC-controller enumeration can produce mmcblk0 or mmcblk1.
    # The header and pinned layout, not a hardcoded index, identify our card.
    for path in sorted(Path('/dev').glob('mmcblk[0-9]')):
        if path.is_symlink() or not path.is_block_device():
            continue
        try:
            return Journal(path)
        except (OSError, ValueError):
            continue
    return None


class Journal:
    """Validated descriptor with writes restricted to two fixed data slots."""
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError('Journal links are forbidden')
        self.fd = os.open(str(path), os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
        try:
            mode = os.fstat(self.fd).st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISBLK(mode)):
                raise ValueError('Invalid journal backing device')
            if len(os.pread(self.fd,1,OFFSET+REGION_BYTES-1))!=1:
                raise ValueError('Truncated training save region')
            if os.pread(self.fd, HEADER_BYTES, OFFSET) != header(os.pread(self.fd, 512, 0)):
                raise ValueError('No matching training journal; no write allowed')
            records = [(i, unpack_slot(os.pread(self.fd, SLOT_BYTES, OFFSET + HEADER_BYTES + i*SLOT_BYTES)))
                       for i in range(2)]
            valid = [(i, r) for i, r in records if r is not None]
            if not valid:
                raise ValueError('Both training saves are damaged; no overwrite allowed')
            self.slot, current = max(valid, key=lambda item: (item[1]['generation'], -item[0]))
            self.generation = current['generation']
            self.payload = current['payload']
            self.recovered = len(valid) != 2
        except Exception:
            os.close(self.fd)
            self.fd = None
            raise

    def write(self, payload):
        generation = self.generation + 1
        if generation >= 2**63:
            raise ValueError('Journal generation exhausted')
        data = pack_slot(generation, payload)
        slot = 1 - self.slot
        offset = OFFSET + HEADER_BYTES + slot*SLOT_BYTES
        written = 0
        while written < len(data):
            n = os.pwrite(self.fd, data[written:], offset + written)
            if n <= 0:
                raise OSError('Incomplete training save')
            written += n
        os.fsync(self.fd)
        if os.pread(self.fd, SLOT_BYTES, offset) != data:
            raise OSError('Training save readback failed')
        self.slot, self.generation = slot, generation
        self.payload = copy.deepcopy(payload)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class TrainingStore:
    """Only a versioned ON preference permits restoring or saving history."""
    SAVE_INTERVAL = 2.0

    def __init__(self, journal=None, journal_factory=None):
        self.journal = journal
        self._journal_factory = journal_factory
        raw = journal.payload if journal else {}
        self.persistent = (raw.get('memory_schema') == 1 and raw.get('persistent_memory') is True
                           and isinstance(raw.get('training'), dict))
        self.data = copy.deepcopy(raw['training']) if self.persistent else {}
        self.status = ('Recovered SD save' if journal.recovered else 'Saved on SD') if self.persistent else 'RAM only'
        self._condition = threading.Condition()
        self._pending = None
        self._busy = False
        self._closed = False
        self._last_error = False
        self._thread = None
        self._changing = False
        self._force = False
        self._next_write = time.monotonic() + self.SAVE_INTERVAL
        if self.persistent:
            self._start_worker()

    def _start_worker(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='training-save', daemon=True)
            self._thread.start()

    @classmethod
    def hardware(cls):
        # Inspect only a matching, preallocated journal. Empty and legacy saves
        # do not opt in, and boot discovery itself never writes the card.
        return cls(hardware_journal(), hardware_journal)

    @staticmethod
    def _record(enabled, data):
        return {'memory_schema': 1, 'persistent_memory': bool(enabled),
                'training': copy.deepcopy(data) if enabled else {}}

    def _commit(self, enabled, data, timeout=3.0):
        """Explicit menu operations finish both copies before reporting success.

        A first committed OFF record already outranks an older ON save if the
        second write is interrupted. Normal gameplay saves stay asynchronous.
        """
        with self._condition:
            if self._closed or self._changing:
                return False
            self._changing = True
            self._pending = None
            until = time.monotonic() + timeout
            while self._busy and time.monotonic() < until:
                self._condition.wait(max(0, until-time.monotonic()))
            if self._busy:
                self._changing = False
                self.status = 'SD busy; try again'
                return False
        committed = False
        try:
            if self.journal is None and self._journal_factory is not None:
                self.journal = self._journal_factory()
            if self.journal is None:
                if enabled:
                    raise OSError('No matching save region')
                committed = True  # RAM-only reset without a card adapter.
            else:
                record = self._record(enabled, data)
                self.journal.write(record)
                committed = True
                self.persistent = bool(enabled)
                self.journal.write(record)
            self.persistent = bool(enabled)
            self.data = copy.deepcopy(data)
            self._last_error = False
            self.status = 'Saved on SD' if enabled else 'RAM only'
            self._next_write = time.monotonic() + self.SAVE_INTERVAL
            if enabled:
                self._start_worker()
            return True
        except (OSError, ValueError):
            if committed:
                self.persistent = bool(enabled)
                self.data = copy.deepcopy(data)
                if enabled:
                    self._start_worker()
            self._last_error = True
            self.status = 'SD change incomplete; retry' if committed else 'SD change failed; retry'
            return False
        finally:
            with self._condition:
                self._changing = False
                self._condition.notify_all()

    def set_persistent(self, enabled):
        return self._commit(bool(enabled), self.data)

    def clear_training(self, empty):
        return self._commit(self.persistent, empty)

    def save(self, data):
        # Encoding/checksumming and disk I/O belong to the background worker.
        value = copy.deepcopy(data)
        with self._condition:
            if self._closed:
                return False
            self.data = value
            if self.persistent and not self._changing:
                self._pending = value
                self.status = 'Saving...'
                self._condition.notify_all()
        return True

    def _run(self):
        while True:
            with self._condition:
                while True:
                    if self._pending is None and self._closed:
                        return
                    if self._pending is not None and not self._changing:
                        delay = self._next_write-time.monotonic()
                        if self._force or self._closed or delay <= 0:
                            break
                        self._condition.wait(delay)
                    else:
                        self._condition.wait()
                if self._pending is None and self._closed:
                    return
                value, self._pending = self._pending, None
                self._busy = True
            try:
                self.journal.write(self._record(True, value))
                message = 'Saved on SD'
                failed = False
            except (OSError, ValueError):
                message = 'SD save failed; kept in RAM'
                failed = True
            with self._condition:
                self._busy = False
                self._last_error = failed
                self._next_write = time.monotonic() + self.SAVE_INTERVAL
                self._force = False
                self.status = message if self._pending is None else 'Saving...'
                self._condition.notify_all()

    def flush(self, timeout=3):
        until = time.monotonic() + timeout
        with self._condition:
            self._force = True
            self._condition.notify_all()
            while (self._pending is not None or self._busy) and time.monotonic() < until:
                self._condition.wait(max(0, until-time.monotonic()))
            return self._pending is None and not self._busy and not self._last_error

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._thread:
            self._thread.join(3)
            if self._thread.is_alive():
                raise RuntimeError('Training save still finishing')
        if self.journal:
            self.journal.close()
