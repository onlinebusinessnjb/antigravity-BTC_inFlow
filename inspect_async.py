
import flet as ft
from flet_webview import WebView
import inspect
import asyncio

print("--- WebView ---")
print("Is run_javascript a coroutine function?", inspect.iscoroutinefunction(WebView.run_javascript))

print("\n--- Page ---")
# Check for _async methods
for name in dir(ft.Page):
    if name.endswith("_async"):
        print(name)

print("\nCheck add:", inspect.iscoroutinefunction(ft.Page.add))
print("Check update:", inspect.iscoroutinefunction(ft.Page.update))
