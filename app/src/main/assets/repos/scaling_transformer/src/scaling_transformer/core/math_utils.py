"""Mathematical utilities for scaling transformer analysis."""

from typing import Union, Tuple
import math


def format_number(num: Union[int, float]) -> str:
    """Format large numbers with appropriate suffixes (K, M, B, T, P).
    
    Args:
        num: Number to format
        
    Returns:
        Formatted string with appropriate suffix
    """
    if num >= 1e15:
        return f"{num/1e15:.2f}P"
    elif num >= 1e12:
        return f"{num/1e12:.2f}T"
    elif num >= 1e9:
        return f"{num/1e9:.2f}B"
    elif num >= 1e6:
        return f"{num/1e6:.2f}M"
    elif num >= 1e3:
        return f"{num/1e3:.2f}K"
    return str(int(num))


def calculate_flops(
    batch_size: int,
    seq_length: int, 
    d_model: int,
    operation: str = "matmul"
) -> int:
    """Calculate FLOPs for common operations.
    
    Args:
        batch_size: Batch size
        seq_length: Sequence length
        d_model: Model dimension
        operation: Type of operation ("matmul", "attention", etc.)
        
    Returns:
        Number of FLOPs
    """
    if operation == "matmul":
        # Standard matrix multiplication: 2 * B * T * D * F
        return 2 * batch_size * seq_length * d_model
    elif operation == "attention":
        # Attention mechanism: 2 * B * T^2 * D
        return 2 * batch_size * seq_length * seq_length * d_model
    else:
        raise ValueError(f"Unsupported operation: {operation}")


def calculate_bytes(
    *dimensions: int,
    precision: str = "bfloat16"
) -> int:
    """Calculate memory usage in bytes for given dimensions and precision.
    
    Args:
        dimensions: Tensor dimensions
        precision: Data precision ("bfloat16", "fp32", "int8", etc.)
        
    Returns:
        Memory usage in bytes
    """
    bytes_per_element = {
        "bfloat16": 2,
        "fp16": 2,
        "fp32": 4,
        "int8": 1,
        "int4": 0.5,
    }
    
    if precision not in bytes_per_element:
        raise ValueError(f"Unsupported precision: {precision}")
    
    total_elements = 1
    for dim in dimensions:
        total_elements *= dim
    
    return int(total_elements * bytes_per_element[precision])


def calculate_arithmetic_intensity(
    flops: int,
    bytes_accessed: int
) -> float:
    """Calculate arithmetic intensity (FLOPs per byte).
    
    Args:
        flops: Number of floating point operations
        bytes_accessed: Number of bytes accessed from memory
        
    Returns:
        Arithmetic intensity (FLOPs/byte)
    """
    if bytes_accessed == 0:
        return float('inf')
    return flops / bytes_accessed


def calculate_roofline_time(
    flops: int,
    bytes_accessed: int,
    peak_flops_per_second: float,
    bandwidth_bytes_per_second: float
) -> Tuple[float, float, bool]:
    """Calculate operation time using roofline model.
    
    Args:
        flops: Number of floating point operations
        bytes_accessed: Number of bytes accessed
        peak_flops_per_second: Peak compute throughput
        bandwidth_bytes_per_second: Memory bandwidth
        
    Returns:
        Tuple of (compute_time, memory_time, is_compute_bound)
    """
    compute_time = flops / peak_flops_per_second
    memory_time = bytes_accessed / bandwidth_bytes_per_second
    
    is_compute_bound = compute_time >= memory_time
    
    return compute_time, memory_time, is_compute_bound


def calculate_communication_time(
    bytes_to_transfer: int,
    bandwidth_bytes_per_second: float,
    num_hops: int = 1,
    latency_per_hop_us: float = 1.0,
    is_bidirectional: bool = True
) -> float:
    """Calculate communication time for network transfers.
    
    Args:
        bytes_to_transfer: Number of bytes to transfer
        bandwidth_bytes_per_second: Network bandwidth
        num_hops: Number of network hops
        latency_per_hop_us: Latency per hop in microseconds
        is_bidirectional: Whether bandwidth is bidirectional
        
    Returns:
        Communication time in seconds
    """
    # Bandwidth-bound time
    if is_bidirectional:
        bandwidth_time = bytes_to_transfer / bandwidth_bytes_per_second
    else:
        bandwidth_time = bytes_to_transfer / (bandwidth_bytes_per_second / 2)
    
    # Latency-bound time
    latency_time = (num_hops * latency_per_hop_us) / 1e6  # Convert to seconds
    
    # Total time is the maximum (assuming we can't overlap)
    return max(bandwidth_time, latency_time)


def optimal_fsdp_mp_split(
    batch_size: int,
    d_ff: int,
    total_chips: int,
    num_axes_fsdp: int = 2,
    num_axes_mp: int = 1
) -> Tuple[int, int]:
    """Calculate optimal FSDP and model parallelism split.
    
    Based on the formula from Section 5:
    X_opt = sqrt(B/F * M_X/M_Y * N)
    
    Args:
        batch_size: Total batch size
        d_ff: Feed-forward dimension
        total_chips: Total number of chips
        num_axes_fsdp: Number of mesh axes for FSDP
        num_axes_mp: Number of mesh axes for model parallelism
        
    Returns:
        Tuple of (optimal_fsdp_chips, optimal_mp_chips)
    """
    ratio = (batch_size / d_ff) * (num_axes_fsdp / num_axes_mp) * total_chips
    x_opt = int(math.sqrt(ratio))
    
    # Ensure we don't exceed total chips
    x_opt = min(x_opt, total_chips)
    y_opt = total_chips // x_opt
    
    return x_opt, y_opt