#!/usr/bin/env python3
"""
Launcher script for Flipper-Pineapple Manager Desktop Application
Installs dependencies and launches the PyQt6 app
"""

import subprocess
import sys
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def install_dependencies():
    """Install required packages"""
    logger.info("Installing dependencies...")
    
    requirements_file = os.path.join(os.path.dirname(__file__), 'requirements-desktop.txt')
    
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', requirements_file])
        logger.info("Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install dependencies: {e}")
        return False

def launch_app():
    """Launch the desktop application"""
    logger.info("Launching Flipper-Pineapple Manager...")
    
    try:
        # Import here so dependencies are already installed
        from desktop_app import main
        main()
    except ImportError as e:
        logger.error(f"Failed to import application: {e}")
        logger.error("Please ensure all dependencies are installed: pip install -r requirements-desktop.txt")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Try to install dependencies first
    if not install_dependencies():
        logger.warning("Some dependencies may not have installed. Attempting to launch anyway...")
    
    # Launch the application
    launch_app()
