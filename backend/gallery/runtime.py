"""A small cross-platform lock for local run/index/delete commands."""
from pathlib import Path
from contextlib import ExitStack
import hashlib
import os
import shutil
import tempfile


class RuntimeLock:
    def __init__(self,data):
        self.data=Path(data).resolve()
        self.file=None

    def __enter__(self):
        lock_root=Path(tempfile.gettempdir())/'fieldnotes-locks'
        if lock_root.resolve().is_relative_to(self.data):
            raise ValueError('The event directory cannot contain the shared runtime lock directory.')
        lock_root.mkdir(parents=True,exist_ok=True)
        name=hashlib.sha256(str(self.data).casefold().encode()).hexdigest()
        self.file=(lock_root/(name+'.lock')).open('a+b')
        self.file.seek(0)
        self.file.write(b'0');self.file.flush();self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();self.file=None
            raise ValueError('This event is already open. Stop the gallery before indexing or deleting it.')
        return self

    def __exit__(self,*_):
        if self.file:
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_UN)
            self.file.close()


def delete_event(data,confirmed=False):
    target=Path(data).resolve()
    if not confirmed:
        raise ValueError('Pass --confirm-delete to delete the entire event directory printed by the command.')
    if target==Path.home().resolve() or Path(__file__).resolve().is_relative_to(target):
        raise ValueError('Refusing to delete a home/source/ancestor directory.')
    if not (target/'organizer.json').is_file() or not (target/'event.sqlite3').is_file():
        raise ValueError('Not a recognized Fieldnotes event directory. Nothing was deleted.')
    with ExitStack() as locks:
        locks.enter_context(RuntimeLock(target))
        if (target/'offline-viewer').exists():locks.enter_context(RuntimeLock(target/'offline-viewer'))
        shutil.rmtree(target)
    return {'deleted':str(target),'scope':'Entire event directory; source photos, source seed ZIP and external model cache are preserved.'}
