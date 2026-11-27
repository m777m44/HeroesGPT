"""
Scaling Transformer: A comprehensive toolkit for understanding and optimizing transformer model scaling.

This package provides implementations and analysis tools for:
- Roofline models and hardware performance analysis
- TPU/GPU architecture understanding  
- Sharded matrix operations and communication primitives
- Transformer math and scaling laws
- Training dynamics and parallelism strategies
- LLaMA-3 specific optimizations

Based on the "How to Scale Your Model" book series.
"""

__version__ = "0.1.0"
__author__ = "Scaling Transformer Team"

from .core.config import Config
from .core.hardware import HardwareSpec

__all__ = [
    "Config",
    "HardwareSpec",
]