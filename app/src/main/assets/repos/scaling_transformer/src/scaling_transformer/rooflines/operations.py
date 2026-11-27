"""Analysis of specific operations for roofline modeling."""

from typing import List, Dict, Any
from dataclasses import dataclass

from .roofline_model import OperationProfile, RooflineModel, RooflineAnalysis
from ..core.config import Config
from ..core.hardware import HardwareSpec


@dataclass
class MatmulAnalysis:
    """Analysis of matrix multiplication operations."""
    
    @staticmethod
    def create_operation(
        batch_size: int,
        input_dim: int,
        output_dim: int,
        precision: str = "bfloat16"
    ) -> OperationProfile:
        """Create operation profile for matrix multiplication.
        
        For operation X[B, D] @ Y[D, F] -> Z[B, F]
        
        Args:
            batch_size: Batch size (B)
            input_dim: Input dimension (D)
            output_dim: Output dimension (F)
            precision: Data precision
            
        Returns:
            Operation profile
        """
        # FLOPs: 2 * B * D * F
        flops = 2 * batch_size * input_dim * output_dim
        
        # Bytes accessed
        bytes_per_element = {"bfloat16": 2, "fp32": 4, "int8": 1}[precision]
        bytes_accessed = bytes_per_element * (
            batch_size * input_dim +    # Load X
            input_dim * output_dim +    # Load Y  
            batch_size * output_dim     # Store Z
        )
        
        return OperationProfile.from_operation(
            name=f"Matmul[{batch_size},{input_dim}]@[{input_dim},{output_dim}]",
            flops=flops,
            bytes_accessed=bytes_accessed
        )
    
    @staticmethod
    def analyze_transformer_matmuls(
        config: Config,
        hardware: HardwareSpec,
        precision: str = "bfloat16"
    ) -> Dict[str, RooflineAnalysis]:
        """Analyze all matrix multiplications in a transformer layer.
        
        Args:
            config: Model configuration
            hardware: Hardware specification
            precision: Data precision
            
        Returns:
            Dictionary of operation name to analysis results
        """
        roofline = RooflineModel(hardware)
        results = {}
        
        # MLP operations
        if config.use_gating:
            # Gated MLP: 3 matrices (W_in1, W_in2, W_out)
            operations = [
                ("MLP Input 1", config.d_model, config.d_ff),
                ("MLP Input 2", config.d_model, config.d_ff), 
                ("MLP Output", config.d_ff, config.d_model),
            ]
        else:
            # Standard MLP: 2 matrices (W_in, W_out)
            operations = [
                ("MLP Input", config.d_model, config.d_ff),
                ("MLP Output", config.d_ff, config.d_model),
            ]
        
        for name, input_dim, output_dim in operations:
            op = MatmulAnalysis.create_operation(
                config.batch_size, input_dim, output_dim, precision
            )
            results[name] = roofline.analyze_operation(op, precision)
        
        # Attention operations
        results["Attention Q"] = roofline.analyze_operation(
            MatmulAnalysis.create_operation(
                config.batch_size, config.d_model, 
                config.n_heads * config.d_qkv, precision
            ), precision
        )
        
        results["Attention K"] = roofline.analyze_operation(
            MatmulAnalysis.create_operation(
                config.batch_size, config.d_model,
                config.n_kv_heads * config.d_qkv, precision  
            ), precision
        )
        
        results["Attention V"] = roofline.analyze_operation(
            MatmulAnalysis.create_operation(
                config.batch_size, config.d_model,
                config.n_kv_heads * config.d_qkv, precision
            ), precision
        )
        
        results["Attention O"] = roofline.analyze_operation(
            MatmulAnalysis.create_operation(
                config.batch_size, config.n_heads * config.d_qkv,
                config.d_model, precision
            ), precision
        )
        
        return results


@dataclass  
class AttentionAnalysis:
    """Analysis of attention operations."""
    
    @staticmethod
    def create_qk_operation(
        batch_size: int,
        seq_length: int,
        n_heads: int,
        d_qkv: int,
        precision: str = "bfloat16"
    ) -> OperationProfile:
        """Create operation profile for Q@K attention computation.
        
        Args:
            batch_size: Batch size
            seq_length: Sequence length
            n_heads: Number of attention heads
            d_qkv: Dimension per head
            precision: Data precision
            
        Returns:
            Operation profile for Q@K computation
        """
        # FLOPs: 2 * B * T * T * N * H
        flops = 2 * batch_size * seq_length * seq_length * n_heads * d_qkv
        
        # Bytes: Load Q and K, store attention scores
        bytes_per_element = {"bfloat16": 2, "fp32": 4, "int8": 1}[precision]
        bytes_accessed = bytes_per_element * (
            batch_size * seq_length * n_heads * d_qkv +  # Q
            batch_size * seq_length * n_heads * d_qkv +  # K
            batch_size * seq_length * seq_length * n_heads  # Attention scores
        )
        
        return OperationProfile.from_operation(
            name=f"Attention QK (T={seq_length})",
            flops=flops,
            bytes_accessed=bytes_accessed
        )
    
    @staticmethod
    def create_sv_operation(
        batch_size: int,
        seq_length: int,
        n_heads: int,
        d_qkv: int,
        precision: str = "bfloat16"
    ) -> OperationProfile:
        """Create operation profile for attention@V computation.
        
        Args:
            batch_size: Batch size
            seq_length: Sequence length  
            n_heads: Number of attention heads
            d_qkv: Dimension per head
            precision: Data precision
            
        Returns:
            Operation profile for attention@V computation
        """
        # FLOPs: 2 * B * T * T * N * H
        flops = 2 * batch_size * seq_length * seq_length * n_heads * d_qkv
        
        # Bytes: Load attention scores and V, store output
        bytes_per_element = {"bfloat16": 2, "fp32": 4, "int8": 1}[precision]
        bytes_accessed = bytes_per_element * (
            batch_size * seq_length * seq_length * n_heads +  # Attention scores
            batch_size * seq_length * n_heads * d_qkv +       # V
            batch_size * seq_length * n_heads * d_qkv         # Output
        )
        
        return OperationProfile.from_operation(
            name=f"Attention SV (T={seq_length})",
            flops=flops,
            bytes_accessed=bytes_accessed
        )
    
    @staticmethod
    def analyze_attention_scaling(
        config: Config,
        hardware: HardwareSpec,
        seq_lengths: List[int],
        precision: str = "bfloat16"
    ) -> Dict[int, Dict[str, RooflineAnalysis]]:
        """Analyze how attention performance scales with sequence length.
        
        Args:
            config: Model configuration
            hardware: Hardware specification
            seq_lengths: List of sequence lengths to analyze
            precision: Data precision
            
        Returns:
            Dictionary mapping sequence length to analysis results
        """
        roofline = RooflineModel(hardware)
        results = {}
        
        for seq_len in seq_lengths:
            seq_results = {}
            
            # QK computation
            qk_op = AttentionAnalysis.create_qk_operation(
                config.batch_size, seq_len, config.n_heads, config.d_qkv, precision
            )
            seq_results["QK"] = roofline.analyze_operation(qk_op, precision)
            
            # SV computation  
            sv_op = AttentionAnalysis.create_sv_operation(
                config.batch_size, seq_len, config.n_heads, config.d_qkv, precision
            )
            seq_results["SV"] = roofline.analyze_operation(sv_op, precision)
            
            results[seq_len] = seq_results
            
        return results


@dataclass
class MLPAnalysis:
    """Analysis of MLP block operations."""
    
    @staticmethod
    def analyze_mlp_scaling(
        hardware: HardwareSpec,
        d_model_values: List[int],
        ff_ratio: float = 4.0,
        batch_size: int = 1024,
        precision: str = "bfloat16"
    ) -> Dict[int, Dict[str, RooflineAnalysis]]:
        """Analyze how MLP performance scales with model dimension.
        
        Args:
            hardware: Hardware specification
            d_model_values: List of model dimensions to analyze
            ff_ratio: Ratio of d_ff to d_model
            batch_size: Batch size
            precision: Data precision
            
        Returns:
            Dictionary mapping d_model to analysis results
        """
        roofline = RooflineModel(hardware)
        results = {}
        
        for d_model in d_model_values:
            d_ff = int(d_model * ff_ratio)
            mlp_results = {}
            
            # Input projection
            input_op = MatmulAnalysis.create_operation(
                batch_size, d_model, d_ff, precision
            )
            mlp_results["Input"] = roofline.analyze_operation(input_op, precision)
            
            # Output projection
            output_op = MatmulAnalysis.create_operation(
                batch_size, d_ff, d_model, precision
            )
            mlp_results["Output"] = roofline.analyze_operation(output_op, precision)
            
            results[d_model] = mlp_results
            
        return results
    
    @staticmethod
    def compare_gated_vs_standard(
        config: Config,
        hardware: HardwareSpec,
        precision: str = "bfloat16"
    ) -> Dict[str, RooflineAnalysis]:
        """Compare gated vs standard MLP performance.
        
        Args:
            config: Model configuration
            hardware: Hardware specification
            precision: Data precision
            
        Returns:
            Comparison of gated vs standard MLP analysis
        """
        roofline = RooflineModel(hardware)
        results = {}
        
        # Standard MLP (2 matrices)
        standard_flops = 2 * (
            2 * config.batch_size * config.d_model * config.d_ff  # W_in + W_out
        )
        standard_bytes = {"bfloat16": 2, "fp32": 4, "int8": 1}[precision] * (
            2 * config.d_model * config.d_ff  # Weights
        )
        
        standard_op = OperationProfile.from_operation(
            "Standard MLP", standard_flops, standard_bytes
        )
        results["Standard"] = roofline.analyze_operation(standard_op, precision)
        
        # Gated MLP (3 matrices) 
        gated_flops = 2 * (
            3 * config.batch_size * config.d_model * config.d_ff  # W_in1 + W_in2 + W_out
        )
        gated_bytes = {"bfloat16": 2, "fp32": 4, "int8": 1}[precision] * (
            3 * config.d_model * config.d_ff  # Weights
        )
        
        gated_op = OperationProfile.from_operation(
            "Gated MLP", gated_flops, gated_bytes
        )
        results["Gated"] = roofline.analyze_operation(gated_op, precision)
        
        return results