import logging
import os
import signal
import threading
from typing import Optional

logger = logging.getLogger("youtube_rss.utils")


class ErrorCatchingThread(threading.Thread):
    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.exc = None

    def run(self):
        self.exc = None
        try:
            self.function(*self.args, **self.kwargs)
        except SystemExit as e:
            logger.error(e)
            raise e
        except Exception as e:
            logger.error(e)
            self.exc = e

    def join(self, timeout: Optional[float] = None) -> None:
        try:
            super().join(timeout)
            if self.exc is not None:
                raise self.exc
        except KeyboardInterrupt:
            pid = os.getpid()
            logger.error("User interrupt detected, killing self, PID = %d", pid)
            os.kill(pid, signal.SIGTERM)

    def get_thread_id(self):
        if hasattr(self, "_thread_id"):
            return self._thread_id
        for thread_id, thread in threading._active.items():
            if thread is self:
                return thread_id
