import subprocess, sys, os
env = os.environ.copy()
env['PYTHONPATH'] = r'D:\wokerTest\deepseekHarness\stock-analyst\backend'
proc = subprocess.Popen(
    [sys.executable, '-m', 'uvicorn', 'app.main:app',
     '--host', '127.0.0.1', '--port', '8300'],
    cwd=r'D:\wokerTest\deepseekHarness\stock-analyst\backend',
    env=env,
    creationflags=0x00000008  # DETACHED_PROCESS
)
print(f'backend started pid={proc.pid}')
