"""Configuration management for scaling transformer analysis."""

from dataclasses import dataclass
from typing import Dict, Any, Optional
import json
from pathlib import Path


@dataclass
class Config:
    """Main configuration class for scaling transformer analysis.
    
    This class holds configuration for model architectures, hardware specs,
    training parameters, and analysis settings.
    """
    
    # Model architecture parameters
    d_model: int = 4096
    d_ff: int = 16384
    n_layers: int = 32
    n_heads: int = 32
    n_kv_heads: int = 32
    d_qkv: int = 128
    vocab_size: int = 50000
    
    # Training parameters
    batch_size: int = 1024
    seq_length: int = 2048
    
    # Hardware configuration
    hardware_type: str = "tpu_v5p"
    num_chips: int = 1
    
    # Analysis settings
    precision: str = "bfloat16"
    use_gating: bool = True
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "Config":
        """Create config from dictionary."""
        return cls(**config_dict)
    
    @classmethod
    def from_json(cls, json_path: str) -> "Config":
        """Load config from JSON file."""
        with open(json_path, 'r') as f:
            config_dict = json.load(f)
        return cls.from_dict(config_dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'd_model': self.d_model,
            'd_ff': self.d_ff,
            'n_layers': self.n_layers,
            'n_heads': self.n_heads,
            'n_kv_heads': self.n_kv_heads,
            'd_qkv': self.d_qkv,
            'vocab_size': self.vocab_size,
            'batch_size': self.batch_size,
            'seq_length': self.seq_length,
            'hardware_type': self.hardware_type,
            'num_chips': self.num_chips,
            'precision': self.precision,
            'use_gating': self.use_gating,
        }
    
    def save_json(self, json_path: str) -> None:
        """Save config to JSON file."""
        with open(json_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def llama3_8b(cls) -> "Config":
        """Create config for LLaMA-3 8B model."""
        return cls(
            d_model=4096,
            d_ff=14336,
            n_layers=32,
            n_heads=32,
            n_kv_heads=8,
            d_qkv=128,
            vocab_size=128256,
        )
    
    @classmethod
    def llama3_70b(cls) -> "Config":
        """Create config for LLaMA-3 70B model."""
        return cls(
            d_model=8192,
            d_ff=28672,
            n_layers=80,
            n_heads=64,
            n_kv_heads=8,
            d_qkv=128,
            vocab_size=128256,
        )
    
    @classmethod
    def llama3_405b(cls) -> "Config":
        """Create config for LLaMA-3 405B model."""
        return cls(
            d_model=16384,
            d_ff=53248,
            n_layers=126,
            n_heads=128,
            n_kv_heads=8,
            d_qkv=128,
            vocab_size=128256,
        )
    
    @classmethod
    def gpt3_175b(cls) -> "Config":
        """Create config for GPT-3 175B model."""
        return cls(
            d_model=12288,
            d_ff=49152,
            n_layers=96,
            n_heads=96,
            n_kv_heads=96,
            d_qkv=128,
            vocab_size=50257,
            use_gating=False,  # GPT-3 doesn't use gating
        )
    
    @classmethod
    def bert_base(cls) -> "Config":
        """Create config for BERT-base model."""
        return cls(
            d_model=768,
            d_ff=3072,
            n_layers=12,
            n_heads=12,
            n_kv_heads=12,
            d_qkv=64,
            vocab_size=30522,
            seq_length=512,
            batch_size=512,
            use_gating=False,  # BERT doesn't use gating
        )