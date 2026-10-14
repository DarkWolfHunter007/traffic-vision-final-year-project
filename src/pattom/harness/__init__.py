"""Pipeline harness: the stages of ARCHITECTURE section 2 as plug-in blocks.

A block declares what it reads and writes (named artifacts, usually files).
The pipeline file (configs/pipeline.yaml) lists the blocks in order; a block
can be switched off, swapped, or rebound to a different input without
touching the others. Blocks from other packages plug in through the
``pattom.blocks`` entry-point group.
"""

from pattom.harness.block import Block, BlockNotReady, RunContext
from pattom.harness.pipeline import Pipeline, PipelineError
from pattom.harness.registry import all_blocks, get_block, register_block

__all__ = [
    "Block",
    "BlockNotReady",
    "Pipeline",
    "PipelineError",
    "RunContext",
    "all_blocks",
    "get_block",
    "register_block",
]
