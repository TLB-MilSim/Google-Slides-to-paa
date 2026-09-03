"""PyInstaller entry point for the console CLI executable."""
import sys
import tlbintelmaker

sys.exit(tlbintelmaker.main_cli(sys.argv[1:]))
