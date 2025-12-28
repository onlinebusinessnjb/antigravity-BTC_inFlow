
from flet_webview import WebView
import inspect

print("Methods of WebView:")
for name, method in inspect.getmembers(WebView, predicate=inspect.isfunction):
    print(name)

if hasattr(WebView, 'evaluate_javascript'):
    print("evaluate_javascript exists")
else:
    print("evaluate_javascript DOES NOT exist")
