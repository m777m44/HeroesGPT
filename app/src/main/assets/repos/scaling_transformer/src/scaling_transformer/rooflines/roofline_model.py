"""Roofline model implementation for performance analysis."""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import numpy as np

from ..core.hardware import HardwareSpec
from ..core.math_utils import calculate_arithmetic_intensity, calculate_roofline_time


@dataclass
class OperationProfile:
    """Profile of a computational operation for roofline analysis."""
    
    name: str
    flops: int
    bytes_accessed: int
    arithmetic_intensity: float
    
    @classmethod
    def from_operation(
        cls,
        name: str,
        flops: int,
        bytes_accessed: int
    ) -> "OperationProfile":
        """Create operation profile from FLOP and byte counts."""
        ai = calculate_arithmetic_intensity(flops, bytes_accessed)
        return cls(name, flops, bytes_accessed, ai)


@dataclass
class RooflineAnalysis:
    """Results of roofline analysis for an operation."""
    
    operation: OperationProfile
    hardware: HardwareSpec
    
    # Timing results
    compute_time: float
    memory_time: float
    actual_time: float
    is_compute_bound: bool
    
    # Performance metrics
    achieved_flops_per_second: float
    memory_utilization: float
    compute_utilization: float
    
    @property
    def bottleneck(self) -> str:
        """Get the performance bottleneck."""
        return "compute" if self.is_compute_bound else "memory"
    
    @property
    def efficiency(self) -> float:
        """Get overall efficiency (0-1)."""
        if self.is_compute_bound:
            return self.compute_utilization
        else:
            return self.memory_utilization


class RooflineModel:
    """Roofline model for performance analysis and prediction."""
    
    def __init__(self, hardware: HardwareSpec):
        """Initialize roofline model with hardware specification.
        
        Args:
            hardware: Hardware specification
        """
        self.hardware = hardware
        
    def analyze_operation(
        self,
        operation: OperationProfile,
        precision: str = "bfloat16"
    ) -> RooflineAnalysis:
        """Analyze operation performance using roofline model.
        
        Args:
            operation: Operation to analyze
            precision: Computation precision
            
        Returns:
            Roofline analysis results
        """
        # Get peak performance for precision
        if precision == "bfloat16":
            peak_flops = self.hardware.bf16_flops_per_second
        elif precision == "int8":
            peak_flops = self.hardware.int8_flops_per_second
        elif precision == "fp32":
            peak_flops = self.hardware.fp32_flops_per_second
        else:
            raise ValueError(f"Unsupported precision: {precision}")
        
        # Calculate times
        compute_time, memory_time, is_compute_bound = calculate_roofline_time(
            operation.flops,
            operation.bytes_accessed,
            peak_flops,
            self.hardware.hbm_bandwidth_bytes_per_second
        )
        
        actual_time = max(compute_time, memory_time)
        achieved_flops_per_second = operation.flops / actual_time
        
        # Calculate utilizations
        compute_utilization = achieved_flops_per_second / peak_flops
        memory_utilization = (operation.bytes_accessed / actual_time) / self.hardware.hbm_bandwidth_bytes_per_second
        
        return RooflineAnalysis(
            operation=operation,
            hardware=self.hardware,
            compute_time=compute_time,
            memory_time=memory_time,
            actual_time=actual_time,
            is_compute_bound=is_compute_bound,
            achieved_flops_per_second=achieved_flops_per_second,
            memory_utilization=memory_utilization,
            compute_utilization=compute_utilization,
        )
    
    def get_roofline_curve(
        self,
        ai_range: Tuple[float, float] = (0.1, 1000),
        num_points: int = 1000,
        precision: str = "bfloat16"
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Generate roofline curve data points.
        
        Args:
            ai_range: Range of arithmetic intensities to plot
            num_points: Number of points in the curve
            precision: Computation precision
            
        Returns:
            Tuple of (arithmetic_intensities, achievable_flops_per_second)
        """
        if precision == "bfloat16":
            peak_flops = self.hardware.bf16_flops_per_second
        elif precision == "int8":
            peak_flops = self.hardware.int8_flops_per_second
        elif precision == "fp32":
            peak_flops = self.hardware.fp32_flops_per_second
        else:
            raise ValueError(f"Unsupported precision: {precision}")
        
        # Log-spaced arithmetic intensities
        ai_values = np.logspace(
            np.log10(ai_range[0]),
            np.log10(ai_range[1]),
            num_points
        )
        
        bandwidth = self.hardware.hbm_bandwidth_bytes_per_second
        peak_ai = peak_flops / bandwidth
        
        # Calculate achievable FLOPs for each AI
        achievable_flops = np.minimum(
            ai_values * bandwidth,  # Memory-bound regime
            peak_flops  # Compute-bound regime
        )
        
        return ai_values, achievable_flops
    
    def get_critical_arithmetic_intensity(
        self,
        precision: str = "bfloat16"
    ) -> float:
        """Get critical arithmetic intensity where compute and memory bound regimes meet.
        
        Args:
            precision: Computation precision
            
        Returns:
            Critical arithmetic intensity
        """
        if precision == "bfloat16":
            peak_flops = self.hardware.bf16_flops_per_second
        elif precision == "int8":
            peak_flops = self.hardware.int8_flops_per_second
        elif precision == "fp32":
            peak_flops = self.hardware.fp32_flops_per_second
        else:
            raise ValueError(f"Unsupported precision: {precision}")
        
        return peak_flops / self.hardware.hbm_bandwidth_bytes_per_second
    
    def predict_batch_size_requirement(
        self,
        d_model: int,
        d_ff: int,
        precision: str = "bfloat16"
    ) -> int:
        """Predict minimum batch size for compute-bound matrix multiplication.
        
        For matmul X[B, D] @ Y[D, F], the arithmetic intensity is approximately B
        when B << D, F. We need AI > critical AI to be compute-bound.
        
        Args:
            d_model: Model dimension
            d_ff: Feed-forward dimension  
            precision: Computation precision
            
        Returns:
            Minimum batch size for compute-bound operation
        """
        critical_ai = self.get_critical_arithmetic_intensity(precision)
        return int(critical_ai)
    
    def analyze_batch_scaling(
        self,
        d_model: int,
        d_ff: int,
        batch_sizes: List[int],
        precision: str = "bfloat16"
    ) -> List[RooflineAnalysis]:
        """Analyze how performance scales with batch size.
        
        Args:
            d_model: Model dimension
            d_ff: Feed-forward dimension
            batch_sizes: List of batch sizes to analyze
            precision: Computation precision
            
        Returns:
            List of roofline analyses for each batch size
        """
        results = []
        
        for batch_size in batch_sizes:
            # Matrix multiplication: X[B, D] @ Y[D, F] -> Z[B, F]
            flops = 2 * batch_size * d_model * d_ff
            
            # Bytes: load X, Y and write Z
            if precision == "bfloat16":
                bytes_per_element = 2
            elif precision == "int8":
                bytes_per_element = 1  
            elif precision == "fp32":
                bytes_per_element = 4
            else:
                raise ValueError(f"Unsupported precision: {precision}")
            
            bytes_accessed = bytes_per_element * (
                batch_size * d_model +  # X
                d_model * d_ff +        # Y
                batch_size * d_ff       # Z
            )
            
            operation = OperationProfile.from_operation(
                name=f"Matmul B={batch_size}",
                flops=flops,
                bytes_accessed=bytes_accessed
            )
            
            analysis = self.analyze_operation(operation, precision)
            results.append(analysis)
            
        return results