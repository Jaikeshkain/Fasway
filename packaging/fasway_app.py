# Entry point for packaged builds (PyInstaller)
import sys

if "--send" in sys.argv:   # Explorer's "Send to phone": hand the files over without loading the whole app
    from fasway.sendto import main
else:
    from fasway.main import main

main()
