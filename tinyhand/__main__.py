import os
import sys

# gtk4-layer-shell has to be loaded before libwayland-client, which from Python means LD_PRELOAD.
LIB = "libgtk4-layer-shell.so"


def _ensure_preload():
    if LIB in os.environ.get("LD_PRELOAD", ""):
        return
    for d in ("/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu"):
        path = os.path.join(d, LIB)
        if os.path.exists(path):
            env = dict(os.environ)
            env["LD_PRELOAD"] = (path + " " + env.get("LD_PRELOAD", "")).strip()
            os.execve(sys.executable, [sys.executable, "-m", "tinyhand", *sys.argv[1:]], env)
    sys.exit("tinyhand: gtk4-layer-shell is not installed (sudo pacman -S gtk4-layer-shell)")


if __name__ == "__main__":
    _ensure_preload()
    from .app import main

    sys.exit(main())
