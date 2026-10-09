import json
import urllib.request


def try_import(code):
    req = urllib.request.Request(
        "http://127.0.0.1:8300/api/strategies", method="POST",
        data=json.dumps({"name": "t", "code": code, "source": "import"}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
        return "unexpected 200"
    except urllib.error.HTTPError as e:
        return json.loads(e.read()).get("detail", "")[:80]


print(try_import('{"cells": [], "metadata": {}}'))
print(try_import("from jqdata import *\ndef on_bar(ctx,bar,i): pass"))
