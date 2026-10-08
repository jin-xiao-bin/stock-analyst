import importlib.util

for m in ["torch", "sentence_transformers", "transformers", "pymilvus", "onnxruntime", "sse_starlette"]:
    print(m, "OK" if importlib.util.find_spec(m) else "MISSING")
