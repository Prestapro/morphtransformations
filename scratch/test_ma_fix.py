import sys
import os
from pathlib import Path

# Add parent directory to sys.path so we can import engine
PARENT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PARENT_DIR))

try:
    from engine.hdc.morpheme_algebra import MorphemeAlgebra
    ma = MorphemeAlgebra()
    print("MorphemeAlgebra initialized successfully")
    print(f"DB path: {ma._db_path}")
    print(f"DB exists: {os.path.exists(ma._db_path)}")
    
    decomp = ma.decompose("а", source="any")
    print(f"Decomposition of 'а': {decomp}")
    
    decomp_wik = ma.decompose("а", source="wiktionary")
    print(f"Wiktionary decomposition of 'а': {decomp_wik}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
