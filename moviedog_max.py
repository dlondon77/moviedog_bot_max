#!/usr/bin/env python
# moviedog_max.py

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.max_adapter import MaxAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

if __name__ == "__main__":
    adapter = MaxAdapter()
    adapter.run()  # maxgram использует синхронный run, не asyncio
