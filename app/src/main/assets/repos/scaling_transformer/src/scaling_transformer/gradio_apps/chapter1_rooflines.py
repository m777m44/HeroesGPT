"""Gradio interface for Chapter 1: Rooflines analysis."""

import gradio as gr
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Tuple, Dict, Any
import io
import base64

from ..core.hardware import get_hardware_spec, list_hardware_types
from ..core.config import Config
from ..rooflines.roofline_model import RooflineModel, OperationProfile
from ..rooflines.operations import MatmulAnalysis, AttentionAnalysis, MLPAnalysis
from ..rooflines.plotting import (
    plot_roofline, 
    plot_arithmetic_intensity_comparison,
    plot_batch_size_scaling,
    plot_precision_comparison
)


def get_roofline_plot(
    hardware_type: str,
    precision: str,
    show_operations: bool,
    batch_size: int,
    d_model: int,
    d_ff: int,
    seq_length: int,
    n_heads: int,
    d_qkv: int
) -> plt.Figure:
    """Generate roofline plot with operations."""
    hardware = get_hardware_spec(hardware_type)
    
    operations = []
    if show_operations:
        # Create representative operations
        # Matrix multiplication
        matmul_op = MatmulAnalysis.create_operation(
            batch_size, d_model, d_ff, precision
        )
        operations.append(matmul_op)
        
        # Attention QK
        attention_qk = AttentionAnalysis.create_qk_operation(
            batch_size, seq_length, n_heads, d_qkv, precision
        )
        operations.append(attention_qk)
        
        # Attention SV
        attention_sv = AttentionAnalysis.create_sv_operation(
            batch_size, seq_length, n_heads, d_qkv, precision
        )
        operations.append(attention_sv)
    
    return plot_roofline(
        hardware=hardware,
        operations=operations if show_operations else None,
        precision=precision,
        title=f"Roofline Model - {hardware.name} ({precision})"
    )


def analyze_operation_performance(
    hardware_type: str,
    precision: str,
    operation_type: str,
    batch_size: int,
    d_model: int,
    d_ff: int,
    seq_length: int,
    n_heads: int,
    d_qkv: int
) -> str:
    """Analyze performance of a specific operation."""
    hardware = get_hardware_spec(hardware_type)
    roofline = RooflineModel(hardware)
    
    # Create operation based on type
    if operation_type == "Matrix Multiplication":
        operation = MatmulAnalysis.create_operation(
            batch_size, d_model, d_ff, precision
        )
    elif operation_type == "Attention QK":
        operation = AttentionAnalysis.create_qk_operation(
            batch_size, seq_length, n_heads, d_qkv, precision
        )
    elif operation_type == "Attention SV":
        operation = AttentionAnalysis.create_sv_operation(
            batch_size, seq_length, n_heads, d_qkv, precision
        )
    else:
        return "Unknown operation type"
    
    # Analyze operation
    analysis = roofline.analyze_operation(operation, precision)
    
    # Format results
    result = f"""
## Operation Analysis: {operation.name}

### Operation Characteristics
- **FLOPs**: {operation.flops:,}
- **Bytes Accessed**: {operation.bytes_accessed:,}
- **Arithmetic Intensity**: {operation.arithmetic_intensity:.2f} FLOPs/byte

### Performance Results
- **Bottleneck**: {analysis.bottleneck.title()}-bound
- **Efficiency**: {analysis.efficiency:.1%}
- **Achieved Performance**: {analysis.achieved_flops_per_second/1e12:.2f} TFLOP/s
- **Compute Time**: {analysis.compute_time*1000:.3f} ms
- **Memory Time**: {analysis.memory_time*1000:.3f} ms
- **Total Time**: {analysis.actual_time*1000:.3f} ms

### Hardware Utilization
- **Compute Utilization**: {analysis.compute_utilization:.1%}
- **Memory Utilization**: {analysis.memory_utilization:.1%}

### Recommendations
"""
    
    # Add recommendations
    critical_ai = roofline.get_critical_arithmetic_intensity(precision)
    if operation.arithmetic_intensity < critical_ai:
        result += f"- **Memory-bound**: Consider increasing batch size or reducing memory accesses\n"
        result += f"- **Critical AI**: {critical_ai:.0f} FLOPs/byte (current: {operation.arithmetic_intensity:.1f})\n"
        min_batch = int(critical_ai * operation.bytes_accessed / operation.flops * batch_size)
        result += f"- **Suggested minimum batch size**: {min_batch}\n"
    else:
        result += f"- **Compute-bound**: Good utilization of hardware resources\n"
        result += f"- **Performance**: Close to peak performance\n"
    
    return result


def get_batch_scaling_plot(
    hardware_type: str,
    precision: str,
    d_model: int,
    d_ff: int
) -> plt.Figure:
    """Generate batch size scaling analysis plot."""
    hardware = get_hardware_spec(hardware_type)
    
    # Generate batch sizes from 1 to 10000
    batch_sizes = [2**i for i in range(0, 14)]  # 1, 2, 4, 8, ..., 8192
    
    return plot_batch_size_scaling(
        hardware=hardware,
        d_model=d_model,
        d_ff=d_ff,
        batch_sizes=batch_sizes,
        precision=precision
    )


def compare_hardware_performance(
    precision: str,
    operation_type: str,
    batch_size: int,
    d_model: int,
    d_ff: int,
    seq_length: int,
    n_heads: int,
    d_qkv: int
) -> str:
    """Compare operation performance across different hardware."""
    # Select representative hardware
    hardware_types = ["tpu_v5p", "tpu_v5e", "h100", "a100"]
    
    results = []
    for hw_type in hardware_types:
        try:
            hardware = get_hardware_spec(hw_type)
            roofline = RooflineModel(hardware)
            
            # Create operation
            if operation_type == "Matrix Multiplication":
                operation = MatmulAnalysis.create_operation(
                    batch_size, d_model, d_ff, precision
                )
            elif operation_type == "Attention QK":
                operation = AttentionAnalysis.create_qk_operation(
                    batch_size, seq_length, n_heads, d_qkv, precision
                )
            elif operation_type == "Attention SV":
                operation = AttentionAnalysis.create_sv_operation(
                    batch_size, seq_length, n_heads, d_qkv, precision
                )
            
            analysis = roofline.analyze_operation(operation, precision)
            
            results.append({
                "hardware": hardware.name,
                "performance_tflops": analysis.achieved_flops_per_second / 1e12,
                "efficiency": analysis.efficiency,
                "bottleneck": analysis.bottleneck,
                "time_ms": analysis.actual_time * 1000
            })
            
        except Exception as e:
            continue
    
    # Format comparison table
    comparison = f"""
## Hardware Performance Comparison
**Operation**: {operation_type}  
**Precision**: {precision}  
**Configuration**: B={batch_size}, D={d_model}, F={d_ff}

| Hardware | Performance | Efficiency | Bottleneck | Time (ms) |
|----------|-------------|------------|------------|-----------|
"""
    
    for result in results:
        comparison += f"| {result['hardware']} | {result['performance_tflops']:.2f} TFLOP/s | {result['efficiency']:.1%} | {result['bottleneck']} | {result['time_ms']:.3f} |\n"
    
    return comparison


def create_rooflines_app() -> gr.Interface:
    """Create the Gradio interface for Chapter 1: Rooflines."""
    
    with gr.Blocks(
        title="Chapter 1: Rooflines Analysis",
        theme=gr.themes.Soft(),
        css="""
        .main-header {
            text-align: center;
            color: #2D5AA6;
            margin-bottom: 20px;
        }
        .section-header {
            color: #1E3A8A;
            border-bottom: 2px solid #E5E7EB;
            padding-bottom: 5px;
            margin: 20px 0 10px 0;
        }
        """
    ) as app:
        
        gr.Markdown("""
        # 📊 Chapter 1: Rooflines Analysis
        
        Welcome to the interactive roofline model analyzer! This tool helps you understand hardware performance limits and bottlenecks for transformer operations.
        
        ## 🎯 What you'll learn:
        - **Roofline Models**: Visualize compute vs memory performance limits
        - **Arithmetic Intensity**: Understand FLOPs/byte ratios for different operations
        - **Hardware Comparison**: Compare TPUs, GPUs across different workloads
        - **Performance Optimization**: Identify bottlenecks and optimization opportunities
        """, elem_classes=["main-header"])
        
        with gr.Tabs():
            # Tab 1: Interactive Roofline Plot
            with gr.TabItem("🏔️ Roofline Visualization"):
                gr.Markdown("## Interactive Roofline Model", elem_classes=["section-header"])
                
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Hardware & Precision")
                        hardware_choice = gr.Dropdown(
                            choices=list_hardware_types(),
                            value="tpu_v5p",
                            label="Hardware Type",
                            info="Select the hardware platform to analyze"
                        )
                        precision_choice = gr.Dropdown(
                            choices=["bfloat16", "int8", "fp32"],
                            value="bfloat16",
                            label="Precision",
                            info="Data precision for operations"
                        )
                        show_ops = gr.Checkbox(
                            value=True,
                            label="Show Operation Points",
                            info="Display specific operations on the roofline"
                        )
                        
                        gr.Markdown("### Model Configuration")
                        batch_size = gr.Slider(
                            minimum=1, maximum=8192, value=1024, step=1,
                            label="Batch Size",
                            info="Number of samples in batch"
                        )
                        d_model = gr.Slider(
                            minimum=256, maximum=16384, value=4096, step=256,
                            label="Model Dimension (D)",
                            info="Hidden dimension size"
                        )
                        d_ff = gr.Slider(
                            minimum=1024, maximum=65536, value=16384, step=1024,
                            label="Feed-Forward Dimension (F)",
                            info="MLP intermediate dimension"
                        )
                        seq_length = gr.Slider(
                            minimum=128, maximum=8192, value=2048, step=128,
                            label="Sequence Length (T)",
                            info="Number of tokens in sequence"
                        )
                        
                        gr.Markdown("### Attention Configuration")
                        n_heads = gr.Slider(
                            minimum=1, maximum=128, value=32, step=1,
                            label="Number of Heads (N)",
                            info="Number of attention heads"
                        )
                        d_qkv = gr.Slider(
                            minimum=32, maximum=256, value=128, step=32,
                            label="Head Dimension (H)",
                            info="Dimension per attention head"
                        )
                    
                    with gr.Column(scale=2):
                        roofline_plot = gr.Plot(label="Roofline Model")
                        
                        # Update plot when parameters change
                        inputs = [
                            hardware_choice, precision_choice, show_ops,
                            batch_size, d_model, d_ff, seq_length, n_heads, d_qkv
                        ]
                        
                        for input_component in inputs:
                            input_component.change(
                                fn=get_roofline_plot,
                                inputs=inputs,
                                outputs=roofline_plot
                            )
                
                # Initialize plot
                app.load(
                    fn=get_roofline_plot,
                    inputs=inputs,
                    outputs=roofline_plot
                )
            
            # Tab 2: Operation Analysis
            with gr.TabItem("🔍 Operation Analysis"):
                gr.Markdown("## Detailed Operation Performance Analysis", elem_classes=["section-header"])
                
                with gr.Row():
                    with gr.Column(scale=1):
                        analysis_hardware = gr.Dropdown(
                            choices=list_hardware_types(),
                            value="tpu_v5p",
                            label="Hardware Type"
                        )
                        analysis_precision = gr.Dropdown(
                            choices=["bfloat16", "int8", "fp32"],
                            value="bfloat16",
                            label="Precision"
                        )
                        operation_type = gr.Dropdown(
                            choices=["Matrix Multiplication", "Attention QK", "Attention SV"],
                            value="Matrix Multiplication",
                            label="Operation Type",
                            info="Type of operation to analyze"
                        )
                        
                        # Reuse model configuration from Tab 1
                        analysis_batch = gr.Slider(
                            minimum=1, maximum=8192, value=1024, step=1,
                            label="Batch Size"
                        )
                        analysis_d_model = gr.Slider(
                            minimum=256, maximum=16384, value=4096, step=256,
                            label="Model Dimension (D)"
                        )
                        analysis_d_ff = gr.Slider(
                            minimum=1024, maximum=65536, value=16384, step=1024,
                            label="Feed-Forward Dimension (F)"
                        )
                        analysis_seq_length = gr.Slider(
                            minimum=128, maximum=8192, value=2048, step=128,
                            label="Sequence Length (T)"
                        )
                        analysis_n_heads = gr.Slider(
                            minimum=1, maximum=128, value=32, step=1,
                            label="Number of Heads (N)"
                        )
                        analysis_d_qkv = gr.Slider(
                            minimum=32, maximum=256, value=128, step=32,
                            label="Head Dimension (H)"
                        )
                        
                        analyze_btn = gr.Button("🔍 Analyze Operation", variant="primary")
                    
                    with gr.Column(scale=2):
                        analysis_results = gr.Markdown(
                            value="Click **Analyze Operation** to see detailed performance analysis.",
                            label="Analysis Results"
                        )
                
                analyze_btn.click(
                    fn=analyze_operation_performance,
                    inputs=[
                        analysis_hardware, analysis_precision, operation_type,
                        analysis_batch, analysis_d_model, analysis_d_ff,
                        analysis_seq_length, analysis_n_heads, analysis_d_qkv
                    ],
                    outputs=analysis_results
                )
            
            # Tab 3: Batch Size Scaling
            with gr.TabItem("📈 Batch Size Scaling"):
                gr.Markdown("## How Performance Scales with Batch Size", elem_classes=["section-header"])
                
                with gr.Row():
                    with gr.Column(scale=1):
                        scaling_hardware = gr.Dropdown(
                            choices=list_hardware_types(),
                            value="tpu_v5p",
                            label="Hardware Type"
                        )
                        scaling_precision = gr.Dropdown(
                            choices=["bfloat16", "int8", "fp32"],
                            value="bfloat16",
                            label="Precision"
                        )
                        scaling_d_model = gr.Slider(
                            minimum=256, maximum=16384, value=4096, step=256,
                            label="Model Dimension (D)"
                        )
                        scaling_d_ff = gr.Slider(
                            minimum=1024, maximum=65536, value=16384, step=1024,
                            label="Feed-Forward Dimension (F)"
                        )
                        
                        scaling_btn = gr.Button("📊 Generate Scaling Analysis", variant="primary")
                    
                    with gr.Column(scale=2):
                        scaling_plot = gr.Plot(label="Batch Size Scaling Analysis")
                
                scaling_btn.click(
                    fn=get_batch_scaling_plot,
                    inputs=[scaling_hardware, scaling_precision, scaling_d_model, scaling_d_ff],
                    outputs=scaling_plot
                )
            
            # Tab 4: Hardware Comparison
            with gr.TabItem("⚖️ Hardware Comparison"):
                gr.Markdown("## Compare Performance Across Hardware", elem_classes=["section-header"])
                
                with gr.Row():
                    with gr.Column(scale=1):
                        comp_precision = gr.Dropdown(
                            choices=["bfloat16", "int8", "fp32"],
                            value="bfloat16",
                            label="Precision"
                        )
                        comp_operation = gr.Dropdown(
                            choices=["Matrix Multiplication", "Attention QK", "Attention SV"],
                            value="Matrix Multiplication",
                            label="Operation Type"
                        )
                        comp_batch = gr.Slider(
                            minimum=1, maximum=8192, value=1024, step=1,
                            label="Batch Size"
                        )
                        comp_d_model = gr.Slider(
                            minimum=256, maximum=16384, value=4096, step=256,
                            label="Model Dimension (D)"
                        )
                        comp_d_ff = gr.Slider(
                            minimum=1024, maximum=65536, value=16384, step=1024,
                            label="Feed-Forward Dimension (F)"
                        )
                        comp_seq_length = gr.Slider(
                            minimum=128, maximum=8192, value=2048, step=128,
                            label="Sequence Length (T)"
                        )
                        comp_n_heads = gr.Slider(
                            minimum=1, maximum=128, value=32, step=1,
                            label="Number of Heads (N)"
                        )
                        comp_d_qkv = gr.Slider(
                            minimum=32, maximum=256, value=128, step=32,
                            label="Head Dimension (H)"
                        )
                        
                        compare_btn = gr.Button("🏆 Compare Hardware", variant="primary")
                    
                    with gr.Column(scale=2):
                        comparison_results = gr.Markdown(
                            value="Click **Compare Hardware** to see performance across different platforms.",
                            label="Hardware Comparison"
                        )
                
                compare_btn.click(
                    fn=compare_hardware_performance,
                    inputs=[
                        comp_precision, comp_operation, comp_batch, comp_d_model,
                        comp_d_ff, comp_seq_length, comp_n_heads, comp_d_qkv
                    ],
                    outputs=comparison_results
                )
        
        gr.Markdown("""
        ---
        ## 💡 Key Insights from Roofline Analysis
        
        - **Arithmetic Intensity** determines whether you're compute or memory bound
        - **Batch size** is crucial for achieving peak performance 
        - **Different operations** have vastly different performance characteristics
        - **Hardware choice** significantly impacts what operations are efficient
        - **Precision** can dramatically change performance bottlenecks
        
        **Next**: Explore Chapter 2 to dive deeper into TPU/GPU architectures!
        """)
    
    return app


def launch_chapter1_app():
    """Launch the Chapter 1 Gradio app."""
    app = create_rooflines_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True
    )


if __name__ == "__main__":
    launch_chapter1_app()