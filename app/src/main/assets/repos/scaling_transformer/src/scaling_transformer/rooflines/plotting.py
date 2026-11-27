"""Plotting utilities for roofline analysis."""

import matplotlib.pyplot as plt
import numpy as np
from typing import List, Dict, Optional, Tuple

from .roofline_model import RooflineModel, RooflineAnalysis, OperationProfile
from ..core.hardware import HardwareSpec
from ..core.math_utils import format_number


def plot_roofline(
    hardware: HardwareSpec,
    operations: Optional[List[OperationProfile]] = None,
    precision: str = "bfloat16",
    ai_range: Tuple[float, float] = (0.1, 1000),
    title: Optional[str] = None,
    figsize: Tuple[int, int] = (12, 8),
    show_critical_ai: bool = True
) -> plt.Figure:
    """Plot roofline model with optional operation points.
    
    Args:
        hardware: Hardware specification
        operations: Optional list of operations to plot
        precision: Computation precision
        ai_range: Range of arithmetic intensities
        title: Plot title
        figsize: Figure size
        show_critical_ai: Whether to show critical AI line
        
    Returns:
        Matplotlib figure
    """
    roofline = RooflineModel(hardware)
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Generate roofline curve
    ai_values, achievable_flops = roofline.get_roofline_curve(
        ai_range=ai_range, precision=precision
    )
    
    # Plot roofline
    ax.loglog(ai_values, achievable_flops, 'b-', linewidth=3, 
              label=f'{hardware.name} Roofline ({precision})')
    
    # Show critical AI
    if show_critical_ai:
        critical_ai = roofline.get_critical_arithmetic_intensity(precision)
        ax.axvline(critical_ai, color='red', linestyle='--', alpha=0.7,
                  label=f'Critical AI = {critical_ai:.0f}')
    
    # Plot operations if provided
    if operations:
        colors = plt.cm.Set1(np.linspace(0, 1, len(operations)))
        
        for i, op in enumerate(operations):
            analysis = roofline.analyze_operation(op, precision)
            
            # Plot operation point
            ax.loglog(op.arithmetic_intensity, analysis.achieved_flops_per_second,
                     'o', color=colors[i], markersize=10, 
                     label=f'{op.name} ({analysis.bottleneck}-bound)')
            
            # Add efficiency annotation
            ax.annotate(f'{analysis.efficiency:.1%}',
                       (op.arithmetic_intensity, analysis.achieved_flops_per_second),
                       xytext=(10, 10), textcoords='offset points',
                       fontsize=9, alpha=0.8)
    
    # Formatting
    ax.set_xlabel('Arithmetic Intensity (FLOPs/byte)', fontsize=12)
    ax.set_ylabel('Performance (FLOPs/s)', fontsize=12)
    
    if title is None:
        title = f'Roofline Model - {hardware.name}'
    ax.set_title(title, fontsize=14, fontweight='bold')
    
    ax.grid(True, alpha=0.3)
    ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    
    # Format y-axis with nice labels
    y_ticks = ax.get_yticks()
    ax.set_yticklabels([format_number(tick) + ' FLOPs/s' for tick in y_ticks])
    
    plt.tight_layout()
    return fig


def plot_arithmetic_intensity_comparison(
    operations: List[OperationProfile],
    hardware: HardwareSpec,
    precision: str = "bfloat16",
    figsize: Tuple[int, int] = (12, 6)
) -> plt.Figure:
    """Plot comparison of arithmetic intensities for different operations.
    
    Args:
        operations: List of operations to compare
        hardware: Hardware specification  
        precision: Computation precision
        figsize: Figure size
        
    Returns:
        Matplotlib figure
    """
    roofline = RooflineModel(hardware)
    critical_ai = roofline.get_critical_arithmetic_intensity(precision)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
    
    # Extract data
    names = [op.name for op in operations]
    ai_values = [op.arithmetic_intensity for op in operations]
    
    # Analyze each operation
    analyses = [roofline.analyze_operation(op, precision) for op in operations]
    efficiencies = [analysis.efficiency for analysis in analyses]
    bottlenecks = [analysis.bottleneck for analysis in analyses]
    
    # Color code by bottleneck
    colors = ['red' if b == 'memory' else 'green' for b in bottlenecks]
    
    # Plot 1: Arithmetic Intensity
    bars1 = ax1.bar(names, ai_values, color=colors, alpha=0.7)
    ax1.axhline(critical_ai, color='blue', linestyle='--', alpha=0.8,
               label=f'Critical AI = {critical_ai:.0f}')
    ax1.set_ylabel('Arithmetic Intensity (FLOPs/byte)')
    ax1.set_title('Arithmetic Intensity by Operation')
    ax1.legend()
    plt.setp(ax1.get_xticklabels(), rotation=45, ha='right')
    
    # Add value labels on bars
    for bar, ai in zip(bars1, ai_values):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + height*0.01,
                f'{ai:.1f}', ha='center', va='bottom', fontsize=9)
    
    # Plot 2: Efficiency
    bars2 = ax2.bar(names, efficiencies, color=colors, alpha=0.7)
    ax2.set_ylabel('Efficiency (%)')
    ax2.set_title('Hardware Utilization Efficiency')
    ax2.set_ylim(0, 1)
    plt.setp(ax2.get_xticklabels(), rotation=45, ha='right')
    
    # Add efficiency labels
    for bar, eff in zip(bars2, efficiencies):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 0.01,
                f'{eff:.1%}', ha='center', va='bottom', fontsize=9)
    
    # Add legend for colors
    memory_patch = plt.Rectangle((0, 0), 1, 1, fc='red', alpha=0.7, label='Memory-bound')
    compute_patch = plt.Rectangle((0, 0), 1, 1, fc='green', alpha=0.7, label='Compute-bound')
    ax2.legend(handles=[memory_patch, compute_patch])
    
    plt.tight_layout()
    return fig


def plot_batch_size_scaling(
    hardware: HardwareSpec,
    d_model: int,
    d_ff: int,
    batch_sizes: List[int],
    precision: str = "bfloat16",
    figsize: Tuple[int, int] = (12, 8)
) -> plt.Figure:
    """Plot how performance scales with batch size.
    
    Args:
        hardware: Hardware specification
        d_model: Model dimension
        d_ff: Feed-forward dimension
        batch_sizes: List of batch sizes to analyze
        precision: Computation precision
        figsize: Figure size
        
    Returns:
        Matplotlib figure
    """
    roofline = RooflineModel(hardware)
    analyses = roofline.analyze_batch_scaling(d_model, d_ff, batch_sizes, precision)
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=figsize)
    
    # Extract data
    ai_values = [a.operation.arithmetic_intensity for a in analyses]
    efficiencies = [a.efficiency for a in analyses]
    achieved_flops = [a.achieved_flops_per_second for a in analyses]
    is_compute_bound = [a.is_compute_bound for a in analyses]
    
    # Colors based on bottleneck
    colors = ['green' if cb else 'red' for cb in is_compute_bound]
    
    # Plot 1: Arithmetic Intensity vs Batch Size
    ax1.semilogx(batch_sizes, ai_values, 'o-', color='blue')
    critical_ai = roofline.get_critical_arithmetic_intensity(precision)
    ax1.axhline(critical_ai, color='red', linestyle='--', alpha=0.7,
               label=f'Critical AI = {critical_ai:.0f}')
    ax1.set_xlabel('Batch Size')
    ax1.set_ylabel('Arithmetic Intensity')
    ax1.set_title('Arithmetic Intensity vs Batch Size')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Efficiency vs Batch Size
    ax2.semilogx(batch_sizes, [e * 100 for e in efficiencies], 'o-', color='purple')
    ax2.set_xlabel('Batch Size')
    ax2.set_ylabel('Efficiency (%)')
    ax2.set_title('Hardware Utilization vs Batch Size')
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Achieved FLOPs vs Batch Size
    ax3.loglog(batch_sizes, achieved_flops, 'o-', color='orange')
    if precision == "bfloat16":
        peak_flops = hardware.bf16_flops_per_second
    elif precision == "int8":
        peak_flops = hardware.int8_flops_per_second
    else:
        peak_flops = hardware.fp32_flops_per_second
        
    ax3.axhline(peak_flops, color='green', linestyle='--', alpha=0.7,
               label=f'Peak = {format_number(peak_flops)} FLOPs/s')
    ax3.set_xlabel('Batch Size')
    ax3.set_ylabel('Achieved FLOPs/s')
    ax3.set_title('Performance vs Batch Size')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # Plot 4: Bottleneck analysis
    memory_bound_count = sum(1 for cb in is_compute_bound if not cb)
    compute_bound_count = sum(1 for cb in is_compute_bound if cb)
    
    ax4.bar(['Memory-bound', 'Compute-bound'], 
           [memory_bound_count, compute_bound_count],
           color=['red', 'green'], alpha=0.7)
    ax4.set_ylabel('Number of Batch Sizes')
    ax4.set_title('Bottleneck Distribution')
    
    # Add counts on bars
    ax4.text(0, memory_bound_count + 0.1, str(memory_bound_count), 
            ha='center', va='bottom')
    ax4.text(1, compute_bound_count + 0.1, str(compute_bound_count),
            ha='center', va='bottom')
    
    plt.suptitle(f'Batch Size Scaling Analysis - {hardware.name}\n'
                f'D={d_model}, F={d_ff}, {precision}', fontsize=14)
    plt.tight_layout()
    return fig


def plot_precision_comparison(
    hardware: HardwareSpec,
    operation: OperationProfile,
    precisions: List[str] = ["fp32", "bfloat16", "int8"],
    figsize: Tuple[int, int] = (10, 6)
) -> plt.Figure:
    """Compare operation performance across different precisions.
    
    Args:
        hardware: Hardware specification
        operation: Operation to analyze
        precisions: List of precisions to compare
        figsize: Figure size
        
    Returns:
        Matplotlib figure
    """
    roofline = RooflineModel(hardware)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
    
    # Analyze operation for each precision
    results = {}
    for precision in precisions:
        analysis = roofline.analyze_operation(operation, precision)
        results[precision] = analysis
    
    # Extract data
    precision_names = list(results.keys())
    achieved_flops = [results[p].achieved_flops_per_second for p in precision_names]
    efficiencies = [results[p].efficiency for p in precision_names]
    bottlenecks = [results[p].bottleneck for p in precision_names]
    
    # Color code by bottleneck
    colors = ['red' if b == 'memory' else 'green' for b in bottlenecks]
    
    # Plot 1: Achieved FLOPs
    bars1 = ax1.bar(precision_names, achieved_flops, color=colors, alpha=0.7)
    ax1.set_ylabel('Achieved FLOPs/s')
    ax1.set_title('Performance by Precision')
    
    # Add value labels
    for bar, flops in zip(bars1, achieved_flops):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                format_number(flops), ha='center', va='bottom', fontsize=9)
    
    # Plot 2: Efficiency
    bars2 = ax2.bar(precision_names, [e * 100 for e in efficiencies], 
                   color=colors, alpha=0.7)
    ax2.set_ylabel('Efficiency (%)')
    ax2.set_title('Hardware Utilization by Precision')
    ax2.set_ylim(0, 100)
    
    # Add efficiency labels
    for bar, eff in zip(bars2, efficiencies):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{eff:.1%}', ha='center', va='bottom', fontsize=9)
    
    # Add legend for colors
    memory_patch = plt.Rectangle((0, 0), 1, 1, fc='red', alpha=0.7, label='Memory-bound')
    compute_patch = plt.Rectangle((0, 0), 1, 1, fc='green', alpha=0.7, label='Compute-bound')
    ax2.legend(handles=[memory_patch, compute_patch])
    
    plt.suptitle(f'Precision Comparison - {operation.name}\n'
                f'AI = {operation.arithmetic_intensity:.1f} FLOPs/byte', 
                fontsize=12)
    plt.tight_layout()
    return fig