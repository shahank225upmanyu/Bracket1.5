import sys
import os

# Put server/ on the path so tests can import core/, ml/, utils/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "server"))
