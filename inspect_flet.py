
import flet as ft
print("WebView in ft:", hasattr(ft, "WebView"))
print("Attributes starting with Web:", [x for x in dir(ft) if x.startswith("Web")])
