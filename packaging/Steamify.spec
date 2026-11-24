# PyInstaller recipe for the desktop app. build_exe.bat runs it; you don't
# need to run it by hand.
#
# A .spec file is plain Python. PyInstaller runs it with Analysis, PYZ, EXE
# and COLLECT already defined, and SPECPATH set to this folder.

import sys
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402  (only for the app's name and version)

# What shows up under Properties > Details on the .exe, and in Task Manager.
# Windows wants the version as four numbers, so 1.0.0 becomes 1.0.0.0.
numbers = tuple(int(part) for part in config.APP_VERSION.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("FileDescription", config.APP_NAME),
                StringStruct("ProductName", config.APP_NAME),
                StringStruct("FileVersion", config.APP_VERSION),
                StringStruct("ProductVersion", config.APP_VERSION),
                StringStruct("InternalName", config.EXE_NAME),
                StringStruct("OriginalFilename", f"{config.EXE_NAME}.exe"),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

analysis = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    # The folders Flask reads while running: (where they are now, where they go in the build)
    datas=[
        (str(ROOT / "templates"), "templates"),
        (str(ROOT / "static"), "static"),
    ],
    # pystray picks its Windows code by name while running, so name it here to be sure it's packed.
    hiddenimports=["pystray._win32"],
)

exe = EXE(
    PYZ(analysis.pure),
    analysis.scripts,
    exclude_binaries=True,  # Python and the libraries go in the _internal folder next to the .exe
    name=config.EXE_NAME,
    console=False,          # no black console window behind the app
    icon=str(ROOT / "static" / "img" / "icon.ico"),
    version=version_info,
)

COLLECT(exe, analysis.binaries, analysis.datas, name=config.EXE_NAME)
