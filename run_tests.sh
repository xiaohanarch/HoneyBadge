#!/bin/bash
cd /mnt/d/dev/HoneyBadge/.worktrees/phase1-implementation
export PATH=/home/xiaolu/.local/bin:$PATH
export HOME=/home/xiaolu
python3 -m pytest tests/ -v
