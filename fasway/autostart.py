"""Start Fasway automatically when you sign in.

Windows: a Task Scheduler task (not the Run registry key) because only a task can start Fasway as
Administrator at sign-in without a UAC prompt every time. Creating an admin task needs one UAC prompt.
macOS: a LaunchAgent.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

TASK = "Fasway"
ROOT = Path(__file__).resolve().parent.parent
MAC_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.fasway.agent.plist"


def launch_command() -> tuple[str, list[str], str]:
    """(program, args, working dir) that starts Fasway silently in the tray."""
    if getattr(sys, "frozen", False):
        return sys.executable, ["--background"], str(Path(sys.executable).parent)
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").exists():
        exe = exe.with_name("pythonw.exe")   # no console window
    return str(exe), ["-m", "fasway", "--background"], str(ROOT)


# ---------------- Windows ----------------

def _schtasks(*args: str) -> int:
    return subprocess.run(["schtasks", *args], capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW).returncode


def _run_elevated_and_wait(exe: str, params: str) -> int:
    """Run a program as Administrator (UAC prompt) and return its exit code (-1 if declined)."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    sei = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x40,  # SEE_MASK_NOCLOSEPROCESS
                            lpVerb="runas", lpFile=exe, lpParameters=params, nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)) or not sei.hProcess:
        return -1
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 30000)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return code.value


def _task_xml(as_admin: bool) -> str:
    prog, args, workdir = launch_command()
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    arg_str = " ".join(f'"{a}"' if " " in a else a for a in args)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Starts Fasway (phone remote) when you sign in.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId><Delay>PT5S</Delay></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType>
    <RunLevel>{"HighestAvailable" if as_admin else "LeastPrivilege"}</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(prog)}</Command><Arguments>{escape(arg_str)}</Arguments>
    <WorkingDirectory>{escape(workdir)}</WorkingDirectory></Exec></Actions>
</Task>"""


def _win_enabled() -> bool:
    return _schtasks("/Query", "/TN", TASK) == 0


def _win_enable(as_admin: bool) -> bool:
    xml = Path(tempfile.gettempdir()) / "fasway-task.xml"
    xml.write_text(_task_xml(as_admin), encoding="utf-16")
    args = ["/Create", "/TN", TASK, "/XML", str(xml), "/F"]
    from .input_win import is_elevated
    if as_admin and not is_elevated():   # an admin task can only be created as admin: one UAC prompt
        ok = _run_elevated_and_wait("schtasks", " ".join(f'"{a}"' if " " in a else a for a in args)) == 0
    else:
        ok = _schtasks(*args) == 0
    xml.unlink(missing_ok=True)
    return ok and _win_enabled()


def _win_disable() -> bool:
    if _schtasks("/Delete", "/TN", TASK, "/F") != 0:
        _run_elevated_and_wait("schtasks", f"/Delete /TN {TASK} /F")   # admin tasks may need admin to delete
    return not _win_enabled()


# ---------------- macOS ----------------

def _mac_enable() -> bool:
    prog, args, workdir = launch_command()
    items = "".join(f"<string>{escape(a)}</string>" for a in [prog, *args])
    MAC_PLIST.parent.mkdir(parents=True, exist_ok=True)
    MAC_PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.fasway.agent</string>
  <key>ProgramArguments</key><array>{items}</array>
  <key>WorkingDirectory</key><string>{escape(workdir)}</string>
  <key>RunAtLoad</key><true/>
</dict></plist>""")
    return True


# ---------------- public ----------------

def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_enabled()
    if sys.platform == "darwin":
        return MAC_PLIST.exists()
    return False


def set_enabled(on: bool, as_admin: bool = False) -> bool:
    """Returns the resulting state."""
    if sys.platform == "win32":
        return _win_enable(as_admin) if on else not _win_disable()
    if sys.platform == "darwin":
        if on:
            return _mac_enable()
        MAC_PLIST.unlink(missing_ok=True)
        return False
    return False
