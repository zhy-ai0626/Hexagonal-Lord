"""启动六角领主：conda activate hexlords && python run.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hexlords.ui.main import main

if __name__ == "__main__":
    main()
