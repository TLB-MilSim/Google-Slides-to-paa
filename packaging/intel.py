"""PyInstaller entry point for the console CLI executable."""
import sys
import intelmaker

sys.exit(intelmaker.main_cli(sys.argv[1:]))
