
from flet_charts import ChartAxis, ChartGridLines
import flet as ft
import inspect

print("--- ChartAxis ---")
print(inspect.signature(ChartAxis.__init__))

print("\n--- ChartGridLines ---")
print(inspect.signature(ChartGridLines.__init__))

print("\n--- flet.app vs flet.run ---")
print(f"Has run: {hasattr(ft, 'run')}")
