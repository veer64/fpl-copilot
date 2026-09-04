# _replace_retry.py -- bounded retry around os.replace for the tmp->final
# atomic-write pattern every ingest/pull writer uses.
#
# WHY: the first unattended deadline build (GW3, 2026-09-04) died on
# PermissionError WinError 5 during os.replace(manifest.tmp -> manifest.csv)
# -- the OneDrive sync client held the destination during the rename. The repo
# has since moved off OneDrive, which removes the demonstrated cause; this
# retry covers the residual class (antivirus scanning a just-written file,
# Windows Search indexing) that can transiently hold a file on a LOCAL disk.
# Unattended deadline runs are the production mode, so a 200ms lock must not
# cost a build.
#
# CONTRACT: retry PermissionError only (the transient-lock signature --
# anything else, e.g. a missing tmp file, raises immediately), a fixed number
# of attempts, short sleeps between; the FINAL failure re-raises the original
# PermissionError untouched. Nothing is ever swallowed.

import os
import time


def replace_with_retry(src, dst, attempts=3, delay=0.2):
    """os.replace(src, dst) with `attempts` tries, `delay` seconds apart.

    Retries PermissionError only; the last failure re-raises loudly."""
    for i in range(attempts):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)
