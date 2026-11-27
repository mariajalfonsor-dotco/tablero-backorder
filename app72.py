"""Tablero Backorder · Yokomotor 72.

Streamlit Cloud no permite dos apps con el mismo archivo principal, así que la sede 72
usa este archivo: fija la sede y ejecuta la misma app (app.py). Así un solo código sirve
para las dos sedes, y cada una guarda sus datos aparte.
"""
import os
import runpy
from pathlib import Path

os.environ["SEDE"] = "72"
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
