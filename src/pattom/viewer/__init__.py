"""Local web app (the Pattom workbench) for the pipeline.

Pages: home (setup status), videos, pipeline (edit, check, run with a live log),
results viewer (video with boxes and tracks), and editors for the hand-made
inputs (counting lines, ground points, signal phase log, detection and tracker
settings). Every save goes through the same loader the pipeline uses. The app
adds no values of its own: positions and timings come from the user, results
from the pipeline.

Served on 127.0.0.1 only, with a per-start token for every change: the footage
shows people and number plates and the privacy handling is still open (O16).
"""

from pattom.viewer.app import create_app

__all__ = ["create_app"]
