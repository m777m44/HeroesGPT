"""TPU architecture analysis and modeling."""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from enum import Enum
import math

from ..core.hardware import HardwareSpec
from ..core.math_utils import format_number, calculate_communication_time


class TPUGeneration(Enum):
    """TPU generation types."""
    V3 = "v3"
    V4P = "v4p"
    V5P = "v5p"
    V5E = "v5e"
    V6E = "v6e"


@dataclass
class TPUTopology:
    """TPU pod topology specification."""
    
    dimensions: Tuple[int, ...]  # Pod dimensions (e.g., (16, 20, 28) for v5p)
    host_topology: Tuple[int, ...]  # TPUs per host
    has_wraparound: bool  # Whether optical switches provide wraparounds
    
    @property
    def total_chips(self) -> int:
        """Total number of chips in the topology."""
        return math.prod(self.dimensions)
    
    @property
    def total_hosts(self) -> int:
        """Total number of hosts in the topology."""
        host_chips = math.prod(self.host_topology)
        return self.total_chips // host_chips
    
    @property
    def max_hops(self) -> int:
        """Maximum number of hops between any two chips."""
        if self.has_wraparound:
            return sum(dim // 2 for dim in self.dimensions)
        else:
            return sum(dim - 1 for dim in self.dimensions)
    
    def get_distance(self, chip1: Tuple[int, ...], chip2: Tuple[int, ...]) -> int:
        """Calculate distance between two chips in the topology.
        
        Args:
            chip1: First chip coordinates
            chip2: Second chip coordinates
            
        Returns:
            Manhattan distance in hops
        """
        if len(chip1) != len(chip2) or len(chip1) != len(self.dimensions):
            raise ValueError("Chip coordinates must match topology dimensions")
        
        distance = 0
        for i, (c1, c2, dim) in enumerate(zip(chip1, chip2, self.dimensions)):
            if self.has_wraparound and dim >= 16:  # Wraparound only for dims >= 16
                direct_dist = abs(c2 - c1)
                wrap_dist = dim - direct_dist
                distance += min(direct_dist, wrap_dist)
            else:
                distance += abs(c2 - c1)
        
        return distance
    
    def get_available_bandwidth(self, num_axes: int) -> float:
        """Get available bandwidth when using multiple axes.
        
        Args:
            num_axes: Number of axes being used simultaneously
            
        Returns:
            Effective bandwidth multiplier
        """
        return min(num_axes, len(self.dimensions))


@dataclass
class TPUMemoryHierarchy:
    """TPU memory hierarchy specification."""
    
    # HBM characteristics
    hbm_capacity_gb: float
    hbm_bandwidth_gbps: float
    
    # VMEM characteristics (on-chip memory)
    vmem_capacity_mb: float
    vmem_bandwidth_multiplier: float  # Relative to HBM
    
    # Cache characteristics
    l1_cache_kb: Optional[float] = None
    l2_cache_mb: Optional[float] = None
    
    @property
    def vmem_bandwidth_gbps(self) -> float:
        """VMEM bandwidth in GB/s."""
        return self.hbm_bandwidth_gbps * self.vmem_bandwidth_multiplier
    
    @property
    def hbm_to_vmem_critical_ai(self) -> float:
        """Critical AI for HBM to VMEM transfers."""
        return self.vmem_bandwidth_multiplier  # Simplified


class TPUAnalysis:
    """Analysis utilities for TPU architectures."""
    
    def __init__(self, hardware: HardwareSpec, generation: TPUGeneration):
        """Initialize TPU analysis.
        
        Args:
            hardware: Hardware specification
            generation: TPU generation
        """
        self.hardware = hardware
        self.generation = generation
        self.topology = self._get_topology()
        self.memory = self._get_memory_hierarchy()
    
    def _get_topology(self) -> TPUTopology:
        """Get topology for the TPU generation."""
        topologies = {
            TPUGeneration.V3: TPUTopology(
                dimensions=(32, 32),
                host_topology=(4, 2),
                has_wraparound=True
            ),
            TPUGeneration.V4P: TPUTopology(
                dimensions=(16, 16, 16),
                host_topology=(2, 2, 1),
                has_wraparound=True
            ),
            TPUGeneration.V5P: TPUTopology(
                dimensions=(16, 20, 28),
                host_topology=(2, 2, 1),
                has_wraparound=True
            ),
            TPUGeneration.V5E: TPUTopology(
                dimensions=(16, 16),
                host_topology=(4, 2),
                has_wraparound=True
            ),
            TPUGeneration.V6E: TPUTopology(
                dimensions=(16, 16),
                host_topology=(4, 2),
                has_wraparound=True
            ),
        }
        return topologies[self.generation]
    
    def _get_memory_hierarchy(self) -> TPUMemoryHierarchy:
        """Get memory hierarchy for the TPU generation."""
        # TPU v5e example (128 MiB VMEM, 22x bandwidth multiplier)
        vmem_specs = {
            TPUGeneration.V3: (32, 10),  # 32 MiB VMEM, 10x bandwidth
            TPUGeneration.V4P: (64, 15),  # 64 MiB VMEM, 15x bandwidth
            TPUGeneration.V5P: (128, 22),  # 128 MiB VMEM, 22x bandwidth
            TPUGeneration.V5E: (128, 22),  # 128 MiB VMEM, 22x bandwidth
            TPUGeneration.V6E: (256, 25),  # 256 MiB VMEM, 25x bandwidth (estimated)
        }
        
        vmem_mb, bandwidth_mult = vmem_specs[self.generation]
        
        return TPUMemoryHierarchy(
            hbm_capacity_gb=self.hardware.hbm_capacity_gb,
            hbm_bandwidth_gbps=self.hardware.hbm_bandwidth_bytes_per_second / 1e9,
            vmem_capacity_mb=vmem_mb,
            vmem_bandwidth_multiplier=bandwidth_mult
        )
    
    def calculate_systolic_array_utilization(
        self,
        matrix_dims: Tuple[int, int],
        precision: str = "bfloat16"
    ) -> float:
        """Calculate systolic array utilization for given matrix dimensions.
        
        The systolic array requires matrices to be padded to at least 128x128
        (256x256 for v6e) for full utilization.
        
        Args:
            matrix_dims: Matrix dimensions (M, N)
            precision: Data precision
            
        Returns:
            Utilization fraction (0-1)
        """
        m, n = matrix_dims
        
        # Systolic array sizes
        if self.generation == TPUGeneration.V6E:
            min_dim = 256
        else:
            min_dim = 128
        
        # Calculate padding overhead
        padded_m = max(m, min_dim)
        padded_n = max(n, min_dim)
        
        utilization = (m * n) / (padded_m * padded_n)
        return min(utilization, 1.0)
    
    def estimate_mxu_performance(
        self,
        batch_size: int,
        input_dim: int,
        output_dim: int,
        precision: str = "bfloat16"
    ) -> Dict[str, float]:
        """Estimate MXU performance for a matrix multiplication.
        
        Args:
            batch_size: Batch size
            input_dim: Input dimension
            output_dim: Output dimension
            precision: Data precision
            
        Returns:
            Performance metrics dictionary
        """
        # Calculate utilization
        utilization = self.calculate_systolic_array_utilization(
            (input_dim, output_dim), precision
        )
        
        # Get peak performance
        if precision == "bfloat16":
            peak_flops = self.hardware.bf16_flops_per_second
        elif precision == "int8":
            peak_flops = self.hardware.int8_flops_per_second
        else:
            peak_flops = self.hardware.fp32_flops_per_second
        
        # Calculate actual performance
        total_flops = 2 * batch_size * input_dim * output_dim
        effective_flops_per_sec = peak_flops * utilization
        compute_time = total_flops / effective_flops_per_sec
        
        # Memory transfer time
        bytes_per_element = {"bfloat16": 2, "int8": 1, "fp32": 4}[precision]
        bytes_transferred = bytes_per_element * (
            batch_size * input_dim +    # Input
            input_dim * output_dim +    # Weights
            batch_size * output_dim     # Output
        )
        memory_time = bytes_transferred / self.hardware.hbm_bandwidth_bytes_per_second
        
        return {
            "systolic_utilization": utilization,
            "compute_time_ms": compute_time * 1000,
            "memory_time_ms": memory_time * 1000,
            "total_time_ms": max(compute_time, memory_time) * 1000,
            "is_compute_bound": compute_time >= memory_time,
            "effective_flops_per_sec": effective_flops_per_sec,
        }
    
    def analyze_vmem_vs_hbm(
        self,
        operation_bytes: int,
        operation_flops: int,
        precision: str = "bfloat16"
    ) -> Dict[str, float]:
        """Analyze performance difference between VMEM and HBM storage.
        
        Args:
            operation_bytes: Bytes accessed in operation
            operation_flops: FLOPs in operation
            precision: Data precision
            
        Returns:
            Performance comparison
        """
        # HBM performance
        hbm_memory_time = operation_bytes / self.hardware.hbm_bandwidth_bytes_per_second
        
        # VMEM performance (if data fits)
        vmem_memory_time = operation_bytes / self.memory.vmem_bandwidth_gbps / 1e9
        vmem_capacity_bytes = self.memory.vmem_capacity_mb * 1024 * 1024
        fits_in_vmem = operation_bytes <= vmem_capacity_bytes
        
        # Compute time (same for both)
        if precision == "bfloat16":
            peak_flops = self.hardware.bf16_flops_per_second
        elif precision == "int8":
            peak_flops = self.hardware.int8_flops_per_second
        else:
            peak_flops = self.hardware.fp32_flops_per_second
        
        compute_time = operation_flops / peak_flops
        
        return {
            "fits_in_vmem": fits_in_vmem,
            "vmem_capacity_mb": self.memory.vmem_capacity_mb,
            "hbm_memory_time_ms": hbm_memory_time * 1000,
            "vmem_memory_time_ms": vmem_memory_time * 1000 if fits_in_vmem else float('inf'),
            "compute_time_ms": compute_time * 1000,
            "hbm_total_time_ms": max(compute_time, hbm_memory_time) * 1000,
            "vmem_total_time_ms": max(compute_time, vmem_memory_time) * 1000 if fits_in_vmem else float('inf'),
            "speedup": hbm_memory_time / vmem_memory_time if fits_in_vmem else 1.0,
        }
    
    def calculate_inference_latency_bound(
        self,
        model_params: int,
        precision: str = "bfloat16"
    ) -> float:
        """Calculate lower bound on inference latency for autoregressive sampling.
        
        Each sampling step must load all parameters from HBM at least once.
        
        Args:
            model_params: Number of model parameters
            precision: Model precision
            
        Returns:
            Minimum latency per token in milliseconds
        """
        bytes_per_param = {"bfloat16": 2, "int8": 1, "fp32": 4}[precision]
        total_bytes = model_params * bytes_per_param
        
        # Time to load all parameters
        load_time = total_bytes / self.hardware.hbm_bandwidth_bytes_per_second
        
        return load_time * 1000  # Convert to milliseconds


def calculate_pod_specs(generation: TPUGeneration) -> Dict[str, any]:
    """Calculate comprehensive specifications for a TPU pod.
    
    Args:
        generation: TPU generation
        
    Returns:
        Dictionary with pod specifications
    """
    from ..core.hardware import get_hardware_spec
    
    hardware_names = {
        TPUGeneration.V3: "tpu_v3",
        TPUGeneration.V4P: "tpu_v4p", 
        TPUGeneration.V5P: "tpu_v5p",
        TPUGeneration.V5E: "tpu_v5e",
        TPUGeneration.V6E: "tpu_v6e",
    }
    
    hardware = get_hardware_spec(hardware_names[generation])
    analysis = TPUAnalysis(hardware, generation)
    
    return {
        "generation": generation.value,
        "total_chips": analysis.topology.total_chips,
        "total_hosts": analysis.topology.total_hosts,
        "chips_per_host": math.prod(analysis.topology.host_topology),
        "pod_dimensions": analysis.topology.dimensions,
        "host_topology": analysis.topology.host_topology,
        "has_wraparound": analysis.topology.has_wraparound,
        "max_hops": analysis.topology.max_hops,
        
        # Compute specs
        "peak_bf16_flops_per_chip": hardware.bf16_flops_per_second,
        "peak_int8_flops_per_chip": hardware.int8_flops_per_second,
        "total_bf16_flops": hardware.bf16_flops_per_second * analysis.topology.total_chips,
        "total_int8_flops": hardware.int8_flops_per_second * analysis.topology.total_chips,
        
        # Memory specs
        "hbm_per_chip_gb": hardware.hbm_capacity_gb,
        "total_hbm_tb": hardware.hbm_capacity_gb * analysis.topology.total_chips / 1024,
        "hbm_bandwidth_per_chip_gbps": hardware.hbm_bandwidth_bytes_per_second / 1e9,
        "total_hbm_bandwidth_tbps": hardware.hbm_bandwidth_bytes_per_second * analysis.topology.total_chips / 1e12,
        "vmem_per_chip_mb": analysis.memory.vmem_capacity_mb,
        "vmem_bandwidth_multiplier": analysis.memory.vmem_bandwidth_multiplier,
        
        # Network specs
        "ici_bandwidth_per_link_gbps": hardware.ici_bandwidth_bytes_per_second / 1e9,
        "dcn_bandwidth_per_host_gbps": hardware.dcn_bandwidth_bytes_per_second / 1e9,
        "pcie_bandwidth_per_chip_gbps": hardware.pcie_bandwidth_bytes_per_second / 1e9,
        "ici_latency_us": hardware.ici_latency_us,
    }