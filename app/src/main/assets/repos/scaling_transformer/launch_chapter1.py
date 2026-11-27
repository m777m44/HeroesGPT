#!/usr/bin/env python3
"""Launch Chapter 1: Rooflines Analysis Gradio App."""

import sys
import os

# Add src to path so we can import the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from scaling_transformer.gradio_apps.chapter1_rooflines import launch_chapter1_app

if __name__ == "__main__":
    print("🚀 Launching Chapter 1: Rooflines Analysis")
    print("📊 Interactive roofline model and performance analysis")
    print("🌐 Access the app at: http://localhost:7860")
    print()
    
    launch_chapter1_app()