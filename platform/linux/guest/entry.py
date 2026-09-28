"""Fixed appliance entry point. The host never executes this file."""
import sys

sys.path.insert(0, "/usr/lib/atlas")
from atlas_guest.agent import main

main()
