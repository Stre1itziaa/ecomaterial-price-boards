# Keep all nine dashboards alive (hub + storage/mlcc/fabric/signal/factor/scenario/rental/csi300).
# Registered in HKCU Run key; safe to run repeatedly: skips ports already up.
# ASCII only. pythonw runs without a console; CREATE_NO_WINDOW hides children.
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent  # 仓库根
import socket
import subprocess

CREATE_NO_WINDOW = 0x08000000

BOARDS = [
    (str(HERE / "hub" / "serve.py"), 8800),
    (str(HERE / "boards" / "storage" / "serve.py"), 8790),
    (str(HERE / "boards" / "mlcc" / "serve.py"), 8792),
    (str(HERE / "boards" / "fabric" / "serve.py"), 8793),
    (str(HERE / "boards" / "signal" / "serve.py"), 8794),
]

def alive(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0

# Children MUST run under python.exe (not pythonw): http.server logs every
# request to stderr, which is None under pythonw -> request crashes, empty reply.
# CREATE_NO_WINDOW gives each child a hidden console, so stderr exists.
PY_EXE = sys.executable   # 用当前解释器,避免硬编码本机 Python 路径

for script, port in BOARDS:
    if alive(port):
        continue
    if not os.path.exists(script):
        continue
    subprocess.Popen(
        [PY_EXE, script],
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
        cwd=os.path.dirname(script),
    )
