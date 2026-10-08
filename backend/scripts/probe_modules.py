import importlib

for m in ["app.api.analysis", "app.api.watch_tasks", "app.api.strategies",
          "app.api.backtests", "app.api.reviews"]:
    try:
        importlib.import_module(m)
        print(m, "OK")
    except ModuleNotFoundError as e:
        print(m, "NOT-YET", e.name)
    except Exception as e:  # noqa: BLE001
        print(m, "ERROR!", repr(e)[:150])
