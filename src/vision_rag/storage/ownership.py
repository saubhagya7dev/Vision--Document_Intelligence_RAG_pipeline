"""One owner for a local library; lock file remains to avoid inode races."""

import sys
from pathlib import Path
from typing import BinaryIO


class LibraryOwnership:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.stream: BinaryIO = (root / ".library.lock").open("a+b")
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError(
                "This local library is already open; run one app process"
            ) from None

    def close(self) -> None:
        self.stream.close()
