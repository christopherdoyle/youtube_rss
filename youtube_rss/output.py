import logging
import subprocess

logger = logging.getLogger(__name__)


def open_url_in_mpv(url: str, max_resolution: int = 1080) -> bool:
    """Open video in MPV using Youtube-DL. Return True if mpv exits successfully, else
    False.
    """
    command = [
        "mpv",
        f"--ytdl-format=bestvideo[height=?{max_resolution}]+bestaudio/best",
        url,
    ]

    mpv_process = None
    try:
        # it is important to pipe outputs to NULL here otherwise output buffer will fill
        # up
        mpv_process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        mpv_process.wait()
        result = mpv_process.poll()
    except KeyboardInterrupt:
        logger.error("User interrupt detected, exiting MPV process")
        if mpv_process is not None:
            mpv_process.kill()
            mpv_process.wait()
        result = -1

    return result == 0
