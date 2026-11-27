"""Hardware specifications and performance characteristics."""

from dataclasses import dataclass
from typing import Dict, Tuple, Optional
from enum import Enum


class HardwareType(Enum):
    """Supported hardware types."""
    TPU_V3 = "tpu_v3"
    TPU_V4P = "tpu_v4p"
    TPU_V5P = "tpu_v5p"
    TPU_V5E = "tpu_v5e"
    TPU_V6E = "tpu_v6e"
    H100 = "h100"
    A100 = "a100"


@dataclass
class HardwareSpec:
    """Hardware specification with performance characteristics.
    
    This class encapsulates all the key hardware parameters needed
    for roofline analysis and performance modeling.
    """
    
    name: str
    
    # Compute characteristics
    bf16_flops_per_second: float  # Peak bfloat16 FLOPs/s
    int8_flops_per_second: float  # Peak int8 FLOPs/s
    fp32_flops_per_second: float  # Peak fp32 FLOPs/s
    
    # Memory characteristics
    hbm_capacity_gb: float  # HBM capacity in GB
    hbm_bandwidth_bytes_per_second: float  # HBM bandwidth in bytes/s
    
    # Network characteristics
    ici_bandwidth_bytes_per_second: float  # ICI bandwidth (bidirectional)
    dcn_bandwidth_bytes_per_second: float  # DCN bandwidth per host
    pcie_bandwidth_bytes_per_second: float  # PCIe bandwidth
    
    # Topology
    max_pod_size: Tuple[int, ...]  # Maximum pod dimensions
    host_topology: Tuple[int, ...]  # TPUs per host
    
    # Latency characteristics
    ici_latency_us: float = 1.0  # ICI latency in microseconds
    
    @property
    def peak_arithmetic_intensity(self) -> float:
        """Calculate peak arithmetic intensity (FLOPs/byte) for bfloat16."""
        return self.bf16_flops_per_second / self.hbm_bandwidth_bytes_per_second
    
    @property
    def critical_batch_size(self) -> int:
        """Critical batch size for compute-bound operations."""
        return int(self.peak_arithmetic_intensity)
    
    def get_bandwidth_bound_batch_size(self, precision: str = "bfloat16") -> int:
        """Get minimum batch size to be compute-bound for given precision."""
        if precision == "bfloat16":
            return int(self.bf16_flops_per_second / self.hbm_bandwidth_bytes_per_second)
        elif precision == "int8":
            return int(self.int8_flops_per_second / self.hbm_bandwidth_bytes_per_second)
        elif precision == "fp32":
            return int(self.fp32_flops_per_second / self.hbm_bandwidth_bytes_per_second)
        else:
            raise ValueError(f"Unsupported precision: {precision}")


# Hardware specifications database
HARDWARE_SPECS: Dict[str, HardwareSpec] = {
    "tpu_v3": HardwareSpec(
        name="TPU v3",
        bf16_flops_per_second=1.4e14,
        int8_flops_per_second=1.4e14,
        fp32_flops_per_second=1.4e14,
        hbm_capacity_gb=32,
        hbm_bandwidth_bytes_per_second=9.0e11,
        ici_bandwidth_bytes_per_second=2e11,
        dcn_bandwidth_bytes_per_second=2.5e10,
        pcie_bandwidth_bytes_per_second=1.5e10,
        max_pod_size=(32, 32),
        host_topology=(4, 2),
    ),
    
    "tpu_v4p": HardwareSpec(
        name="TPU v4p",
        bf16_flops_per_second=2.75e14,
        int8_flops_per_second=2.75e14,
        fp32_flops_per_second=2.75e14,
        hbm_capacity_gb=32,
        hbm_bandwidth_bytes_per_second=1.2e12,
        ici_bandwidth_bytes_per_second=9e10,
        dcn_bandwidth_bytes_per_second=2.5e10,
        pcie_bandwidth_bytes_per_second=1.5e10,
        max_pod_size=(16, 16, 16),
        host_topology=(2, 2, 1),
    ),
    
    "tpu_v5p": HardwareSpec(
        name="TPU v5p",
        bf16_flops_per_second=4.59e14,
        int8_flops_per_second=9.18e14,
        fp32_flops_per_second=4.59e14,
        hbm_capacity_gb=96,
        hbm_bandwidth_bytes_per_second=2.8e12,
        ici_bandwidth_bytes_per_second=1.8e11,
        dcn_bandwidth_bytes_per_second=2.5e10,
        pcie_bandwidth_bytes_per_second=1.5e10,
        max_pod_size=(16, 20, 28),
        host_topology=(2, 2, 1),
    ),
    
    "tpu_v5e": HardwareSpec(
        name="TPU v5e",
        bf16_flops_per_second=1.97e14,
        int8_flops_per_second=3.94e14,
        fp32_flops_per_second=1.97e14,
        hbm_capacity_gb=16,
        hbm_bandwidth_bytes_per_second=8.1e11,
        ici_bandwidth_bytes_per_second=9e10,
        dcn_bandwidth_bytes_per_second=2.5e10,
        pcie_bandwidth_bytes_per_second=1.5e10,
        max_pod_size=(16, 16),
        host_topology=(4, 2),
    ),
    
    "tpu_v6e": HardwareSpec(
        name="TPU v6e (Trillium)",
        bf16_flops_per_second=9.20e14,
        int8_flops_per_second=1.84e15,
        fp32_flops_per_second=9.20e14,
        hbm_capacity_gb=32,
        hbm_bandwidth_bytes_per_second=1.6e12,
        ici_bandwidth_bytes_per_second=1.8e11,
        dcn_bandwidth_bytes_per_second=2.5e10,
        pcie_bandwidth_bytes_per_second=1.5e10,
        max_pod_size=(16, 16),
        host_topology=(4, 2),
    ),
    
    "h100": HardwareSpec(
        name="NVIDIA H100",
        bf16_flops_per_second=9.89e14,  # Without sparsity
        int8_flops_per_second=1.979e15,  # Without sparsity
        fp32_flops_per_second=6.7e13,
        hbm_capacity_gb=80,
        hbm_bandwidth_bytes_per_second=3.35e12,
        ici_bandwidth_bytes_per_second=4.5e11,  # NVLink
        dcn_bandwidth_bytes_per_second=2.5e10,
        pcie_bandwidth_bytes_per_second=6.4e10,  # PCIe 5.0
        max_pod_size=(256,),  # Single-dimension switch
        host_topology=(8,),
    ),
    
    "a100": HardwareSpec(
        name="NVIDIA A100",
        bf16_flops_per_second=3.12e14,
        int8_flops_per_second=6.24e14,
        fp32_flops_per_second=1.56e13,
        hbm_capacity_gb=40,  # 40GB variant
        hbm_bandwidth_bytes_per_second=1.6e12,
        ici_bandwidth_bytes_per_second=3e11,  # NVLink
        dcn_bandwidth_bytes_per_second=2.5e10,
        pcie_bandwidth_bytes_per_second=3.2e10,  # PCIe 4.0
        max_pod_size=(256,),  # Single-dimension switch
        host_topology=(8,),
    ),
}


def get_hardware_spec(hardware_type: str) -> HardwareSpec:
    """Get hardware specification by type."""
    if hardware_type not in HARDWARE_SPECS:
        raise ValueError(f"Unknown hardware type: {hardware_type}. "
                        f"Available types: {list(HARDWARE_SPECS.keys())}")
    return HARDWARE_SPECS[hardware_type]


def list_hardware_types() -> list[str]:
    """List all available hardware types."""
    return list(HARDWARE_SPECS.keys())