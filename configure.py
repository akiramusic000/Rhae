#!/usr/bin/env python3

###
# Generates build files for the project.
# This file also includes the project configuration,
# such as compiler flags and the object matching status.
#
# Usage:
#   python3 configure.py
#   ninja
#
# Append --help to see available options.
###

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

from tools.project import (
    Object,
    ProgressCategory,
    ProjectConfig,
    calculate_progress,
    generate_build,
    is_windows,
)

# Game versions
DEFAULT_VERSION = 0
VERSIONS = [
    "RHAE01",  # 0
]

parser = argparse.ArgumentParser()
parser.add_argument(
    "mode",
    choices=["configure", "progress"],
    default="configure",
    help="script mode (default: configure)",
    nargs="?",
)
parser.add_argument(
    "-v",
    "--version",
    choices=VERSIONS,
    type=str.upper,
    default=VERSIONS[DEFAULT_VERSION],
    help="version to build",
)
parser.add_argument(
    "--build-dir",
    metavar="DIR",
    type=Path,
    default=Path("build"),
    help="base build directory (default: build)",
)
parser.add_argument(
    "--binutils",
    metavar="BINARY",
    type=Path,
    help="path to binutils (optional)",
)
parser.add_argument(
    "--compilers",
    metavar="DIR",
    type=Path,
    help="path to compilers (optional)",
)
parser.add_argument(
    "--map",
    action="store_true",
    help="generate map file(s)",
)
parser.add_argument(
    "--debug",
    action="store_true",
    help="build with debug info (non-matching)",
)
if not is_windows():
    parser.add_argument(
        "--wrapper",
        metavar="BINARY",
        type=Path,
        help="path to wibo or wine (optional)",
    )
parser.add_argument(
    "--dtk",
    metavar="BINARY | DIR",
    type=Path,
    help="path to decomp-toolkit binary or source (optional)",
)
parser.add_argument(
    "--objdiff",
    metavar="BINARY | DIR",
    type=Path,
    help="path to objdiff-cli binary or source (optional)",
)
parser.add_argument(
    "--sjiswrap",
    metavar="EXE",
    type=Path,
    help="path to sjiswrap.exe (optional)",
)
parser.add_argument(
    "--ninja",
    metavar="BINARY",
    type=Path,
    help="path to ninja binary (optional)",
)
parser.add_argument(
    "--verbose",
    action="store_true",
    help="print verbose output",
)
parser.add_argument(
    "--non-matching",
    dest="non_matching",
    action="store_true",
    help="builds equivalent (but non-matching) or modded objects",
)
parser.add_argument(
    "--warn",
    dest="warn",
    type=str,
    choices=["all", "off", "error"],
    help="how to handle warnings",
)
parser.add_argument(
    "--no-progress",
    dest="progress",
    action="store_false",
    help="disable progress calculation",
)
args = parser.parse_args()

config = ProjectConfig()
config.version = str(args.version)
version_num = VERSIONS.index(config.version)

# Apply arguments
config.build_dir = args.build_dir
config.dtk_path = args.dtk
config.objdiff_path = args.objdiff
config.binutils_path = args.binutils
config.compilers_path = args.compilers
config.generate_map = args.map
config.non_matching = args.non_matching
config.sjiswrap_path = args.sjiswrap
config.ninja_path = args.ninja
config.progress = args.progress
if not is_windows():
    config.wrapper = args.wrapper
# Don't build asm unless we're --non-matching
if not config.non_matching:
    config.asm_dir = None

# Tool versions
config.binutils_tag = "2.42-1"
config.compilers_tag = "20250812"
config.dtk_tag = "v1.7.1"
config.objdiff_tag = "v3.4.1"
config.sjiswrap_tag = "v1.2.2"
config.wibo_tag = "1.0.0-beta.5"

# Project
config.config_path = Path("config") / config.version / "config.yml"
config.check_sha_path = Path("config") / config.version / "build.sha1"
config.asflags = [
    "-mgekko",
    "--strip-local-absolute",
    "-I include",
    f"-I build/{config.version}/include",
    f"--defsym BUILD_VERSION={version_num}",
]
config.ldflags = [
    "-fp hardware",
    "-nodefaults",
]
if args.debug:
    config.ldflags.append("-g")  # Or -gdwarf-2 for Wii linkers
if args.map:
    config.ldflags.append("-mapunused")
    # config.ldflags.append("-listclosure") # For Wii linkers

# Use for any additional files that should cause a re-configure when modified
config.reconfig_deps = []

# Optional numeric ID for decomp.me preset
# Can be overridden in libraries or objects
config.scratch_preset_id = None

# Base flags, common to most GC/Wii games.
# Generally leave untouched, with overrides added below.
cflags_base = [
    "-nodefaults",
    "-proc gekko",
    "-align powerpc",
    "-enum int",
    "-fp hardware",
    "-Cpp_exceptions off",
    # "-W all",
    "-O4,p",
    "-inline auto",
    '-pragma "cats off"',
    '-pragma "warn_notinlined off"',
    "-maxerrors 1",
    "-nosyspath",
    "-RTTI off",
    "-fp_contract on",
    "-str reuse",
    "-enc SJIS",
    "-i include",
    "-i include/MSL",
    "-i include/MSL/internal",
    "-ir include/revolution/BTE",
    f"-i build/{config.version}/include",
    f"-DBUILD_VERSION={version_num}",
    f"-DVERSION_{config.version}",
    "-DREVOLUTION",
]

# Debug flags
if args.debug:
    # Or -sym dwarf-2 for Wii compilers
    cflags_base.extend(["-sym on", "-DDEBUG=1"])
else:
    cflags_base.append("-DNDEBUG=1")

# Warning flags
if args.warn == "all":
    cflags_base.append("-W all")
elif args.warn == "off":
    cflags_base.append("-W off")
elif args.warn == "error":
    cflags_base.append("-W error")

# Metrowerks library flags
cflags_runtime = [
    *cflags_base,
    "-use_lmw_stmw on",
    "-str reuse,pool,readonly",
    "-gccinc",
    "-common off",
    "-inline auto",
]

# RVL SDK flags
cflags_rvl = [
    *cflags_base,
    "-enc SJIS",
    "-fp_contract off",
    "-ipa file",
]

config.linker_version = "GC/3.0a5.2"


# Helper function for Dolphin libraries
def DolphinLib(lib_name: str, objects: List[Object]) -> Dict[str, Any]:
    return {
        "lib": lib_name,
        "mw_version": "GC/1.2.5n",
        "cflags": cflags_base,
        "progress_category": "sdk",
        "objects": objects,
    }

Matching = True                   # Object matches and should be linked
NonMatching = False               # Object does not match and should not be linked
Equivalent = config.non_matching  # Object should be linked when configured with --non-matching


# Object is only matching for specific versions
def MatchingFor(*versions):
    return config.version in versions


config.warn_missing_config = True
config.warn_missing_source = False
config.libs = [
    {
        "lib": "Runtime.PPCEABI.H",
        "mw_version": config.linker_version,
        "cflags": cflags_runtime,
        "progress_category": "sdk",  # str | List[str]
        "objects": [
            Object(Matching, "runtime/__mem.c"),
            Object(Matching, "runtime/__va_arg.c"),
            Object(Matching, "runtime/global_destructor_chain.c"),
            Object(NonMatching, "runtime/NMWException.cpp", extra_cflags=["-Cpp_exceptions on"]),
            Object(Matching, "runtime/ptmf.c"),
            Object(Matching, "runtime/runtime.c"),
            Object(NonMatching, "runtime/__init_cpp_exceptions.cpp"),
            Object(Matching, "runtime/Gecko_ExceptionPPC.c"),
            Object(Matching, "runtime/GCN_mem_alloc.c"),
        ],
    },
    {
        "lib": "RVL_SDK",
        "mw_version": config.linker_version,
        "cflags": cflags_rvl,
        "progress_category": "sdk", # str | List[str]
        "objects": [
            Object(NonMatching, "revolution/NdevExi2AD/DebuggerDriver.c"),
            Object(Matching, "revolution/NdevExi2AD/exi2.c"),
            Object(NonMatching, "revolution/KPAD/KPAD.c"),
            Object(Matching, "revolution/PAD/Pad.c"),
            Object(NonMatching, "revolution/WPAD/WPAD.c"),
            Object(NonMatching, "revolution/WPAD/WPADHIDParser.c"),
            Object(NonMatching, "revolution/WPAD/WPADEncrypt.c"),
            Object(NonMatching, "revolution/WPAD/WPADMem.c"),
            Object(Matching, "revolution/WPAD/debug_msg.c"),
            Object(Matching, "revolution/EUART/euart.c"),
            Object(Matching, "revolution/EXI/EXIBios.c",
                   extra_cflags=["-schedule off"]),
            Object(Matching, "revolution/EXI/EXIUart.c"),
            Object(Matching, "revolution/EXI/EXICommon.c"),
            Object(Matching, "revolution/FS/fs.c"),
            Object(NonMatching, "revolution/GX/GXInit.c"),
            Object(NonMatching, "revolution/GX/GXFifo.c"),
            Object(Matching, "revolution/GX/GXAttr.c"),
            Object(NonMatching, "revolution/GX/GXMisc.c"),
            Object(Matching, "revolution/GX/GXGeometry.c"),
            Object(NonMatching, "revolution/GX/GXFrameBuf.c"),
            Object(Matching, "revolution/GX/GXLight.c"),
            Object(NonMatching, "revolution/GX/GXTexture.c"),
            Object(Matching, "revolution/GX/GXBump.c"),
            Object(NonMatching, "revolution/GX/GXTev.c"),
            Object(Matching, "revolution/GX/GXPixel.c"),
            Object(Matching, "revolution/GX/GXDraw.c"),
            Object(Matching, "revolution/GX/GXDisplayList.c"),
            Object(Matching, "revolution/GX/GXTransform.c"),
            Object(NonMatching, "revolution/GX/GXPerf.c"),
            Object(Matching, "revolution/IPC/ipcMain.c"),
            Object(Matching, "revolution/IPC/ipcclt.c"),
            Object(Matching, "revolution/IPC/memory.c"),
            Object(Matching, "revolution/IPC/ipcProfile.c"),
            Object(Matching, "revolution/MEM/mem_heapCommon.c"),
            Object(NonMatching, "revolution/MEM/mem_expHeap.c"),
            Object(Matching, "revolution/MEM/mem_frameHeap.c"),
            Object(Matching, "revolution/MEM/mem_allocator.c"),
            Object(Matching, "revolution/MEM/mem_list.c"),
            Object(NonMatching, "revolution/MTX/mtx.c"),
            Object(Matching, "revolution/MTX/mtxvec.c"),
            Object(Matching, "revolution/MTX/mtx44.c"),
            Object(Matching, "revolution/MTX/vec.c"),
            Object(Matching, "revolution/MTX/quat.c"),
            Object(Matching, "revolution/NAND/nand.c"),
            Object(Matching, "revolution/NAND/NANDOpenClose.c"),
            Object(Matching, "revolution/NAND/NANDCore.c"),
            Object(Matching, "revolution/NAND/NANDCheck.c"),
            Object(Matching, "revolution/OS/OS.c"),
            Object(Matching, "revolution/OS/OSAlarm.c"),
            Object(Matching, "revolution/OS/OSAlloc.c"),
            Object(Matching, "revolution/OS/OSArena.c"),
            Object(Matching, "revolution/OS/OSAudioSystem.c"),
            Object(Matching, "revolution/OS/OSCache.c"),
            Object(Matching, "revolution/OS/OSContext.c"),
            Object(NonMatching, "revolution/OS/OSError.c"),
            Object(Matching, "revolution/OS/OSExec.c"),
            Object(Matching, "revolution/OS/OSFatal.c"),
            Object(Matching, "revolution/OS/OSFont.c"),
            Object(Matching, "revolution/OS/OSInterrupt.c"),
            Object(Matching, "revolution/OS/OSLink.c"),
            Object(Matching, "revolution/OS/OSMessage.c"),
            Object(Matching, "revolution/OS/OSMemory.c"),
            Object(Matching, "revolution/OS/OSMutex.c"),
            Object(Matching, "revolution/OS/OSReset.c"),
            Object(Matching, "revolution/OS/OSRtc.c"),
            Object(Matching, "revolution/OS/OSSync.c"),
            Object(Matching, "revolution/OS/OSThread.c"),
            Object(Matching, "revolution/OS/OSTime.c"),
            Object(Matching, "revolution/OS/OSUtf.c"),
            Object(Matching, "revolution/OS/OSIpc.c"),
            Object(Matching, "revolution/OS/OSStateTM.c"),
            Object(Matching, "revolution/OS/__start.c"),
            Object(Matching, "revolution/OS/OSPlayRecord.c"),
            Object(Matching, "revolution/OS/OSStateFlags.c"),
            Object(Matching, "revolution/OS/OSNet.c"),
            Object(Matching, "revolution/OS/__ppc_eabi_init.c"),
            Object(Matching, "revolution/SC/scsystem.c"),
            Object(Matching, "revolution/SC/scapi.c"),
            Object(Matching, "revolution/SC/scapi_prdinfo.c"),
            Object(Matching, "revolution/USB/usb.c"),
            Object(NonMatching, "revolution/VI/vi.c"),
            Object(NonMatching, "revolution/VI/i2c.c"),
            Object(NonMatching, "revolution/VI/vi3in1.c"),
            Object(Matching, "revolution/WUD/WUD.c"),
            Object(Matching, "revolution/WUD/WUDHidHost.c"),
            Object(Matching, "revolution/WUD/debug_msg.c"),
            Object(Matching, "revolution/AI/ai.c"),
            Object(Matching, "revolution/ARC/arc.c"),
            Object(Matching, "revolution/AX/AX.c"),
            Object(Matching, "revolution/AX/AXAlloc.c"),
            Object(Matching, "revolution/AX/AXAux.c"),
            Object(Matching, "revolution/AX/AXCL.c"),
            Object(Matching, "revolution/AX/AXOut.c"),
            Object(Matching, "revolution/AX/AXSPB.c"),
            Object(Matching, "revolution/AX/AXVPB.c"),
            Object(Matching, "revolution/AX/AXComp.c"),
            Object(Matching, "revolution/AX/DSPCode.c"),
            Object(Matching, "revolution/AX/AXProf.c"),
            Object(Matching, "revolution/AXFX/AXFXReverbHi.c"),
            Object(Matching, "revolution/AXFX/AXFXReverbHiDpl2.c"),
            Object(NonMatching, "revolution/AXFX/AXFXReverbHiExp.c"),
            Object(NonMatching, "revolution/AXFX/AXFXReverbHiExpDpl2.c"),
            Object(Matching, "revolution/AXFX/AXFXDelay.c"),
            Object(Matching, "revolution/AXFX/AXFXChorus.c"),
            Object(NonMatching, "revolution/AXFX/AXFXChorusExp.c"),
            Object(Matching, "revolution/AXFX/AXFXLfoTable.c"),
            Object(Matching, "revolution/AXFX/AXFXSrcCoef.c"),
            Object(Matching, "revolution/AXFX/AXFXHooks.c"),
            Object(Matching, "revolution/BASE/PPCArch.c"),
            Object(NonMatching, "revolution/BTE/bte_unsplit.c"),
            Object(Matching, "revolution/DB/db.c"),
            Object(Matching, "revolution/DSP/dsp.c"),
            Object(Matching, "revolution/DSP/dsp_debug.c"),
            Object(Matching, "revolution/DSP/dsp_task.c"),
            Object(Matching, "revolution/DVD/dvdfs.c"),
            Object(Matching, "revolution/DVD/dvd.c"),
            Object(Matching, "revolution/DVD/dvdqueue.c"),
            Object(Matching, "revolution/DVD/dvderror.c"),
            Object(Matching, "revolution/DVD/dvdidutils.c"),
            Object(Matching, "revolution/DVD/dvdFatal.c"),
            Object(Matching, "revolution/DVD/dvd_broadway.c"),
            Object(NonMatching, "revolution/SI/SIBios.c"),
            Object(Matching, "revolution/SI/SISamplingRate.c"),
            Object(Matching, "revolution/TPL/TPL.c"),
            Object(Matching, "revolution/WENC/wenc.c"),
            Object(NonMatching, "revolution/CNT/cnt.c"),
            Object(Matching, "revolution/ESP/esp.c"),
            Object(NonMatching, "revolution/NET/nettime.c"),
            Object(NonMatching, "revolution/NET/NETVersion.c"),
            Object(NonMatching, "revolution/NWC24/NWC24StdApi.c"),
            Object(Matching, "revolution/NWC24/NWC24FileApi.c"),
            Object(Matching, "revolution/NWC24/NWC24Config.c"),
            Object(Matching, "revolution/NWC24/NWC24Utils.c"),
            Object(Matching, "revolution/NWC24/NWC24Manage.c"),
            Object(Matching, "revolution/NWC24/NWC24MsgObj.c"),
            Object(NonMatching, "revolution/NWC24/NWC24MBoxCtrl.c"),
            Object(NonMatching, "revolution/NWC24/NWC24Mime.c"),
            Object(Matching, "revolution/NWC24/NWC24Parser.c"),
            Object(NonMatching, "revolution/NWC24/NWC24MsgCommit.c"),
            Object(Matching, "revolution/NWC24/NWC24Schedule.c"),
            Object(NonMatching, "revolution/NWC24/NWC24DateParser.c"),
            Object(Matching, "revolution/NWC24/NWC24FriendList.c"),
            Object(Matching, "revolution/NWC24/NWC24SecretFList.c"),
            Object(Matching, "revolution/NWC24/NWC24Time.c"),
            Object(Matching, "revolution/NWC24/NWC24Ipc.c"),
            Object(Matching, "revolution/NWC24/NWC24Download.c"),
            Object(Matching, "revolution/NWC24/NWC24System.c"),
        ],
    },
]


# Optional callback to adjust link order. This can be used to add, remove, or reorder objects.
# This is called once per module, with the module ID and the current link order.
#
# For example, this adds "dummy.c" to the end of the DOL link order if configured with --non-matching.
# "dummy.c" *must* be configured as a Matching (or Equivalent) object in order to be linked.
def link_order_callback(module_id: int, objects: List[str]) -> List[str]:
    # Don't modify the link order for matching builds
    if not config.non_matching:
        return objects
    if module_id == 0:  # DOL
        return objects + ["dummy.c"]
    return objects


# Uncomment to enable the link order callback.
# config.link_order_callback = link_order_callback


# Optional extra categories for progress tracking
# Adjust as desired for your project
config.progress_categories = [
    ProgressCategory("game", "Game Code"),
    ProgressCategory("sdk", "SDK Code"),
]
config.progress_each_module = args.verbose
# Optional extra arguments to `objdiff-cli report generate`
config.progress_report_args = [
    # Marks relocations as mismatching if the target value is different
    # Default is "functionRelocDiffs=none", which is most lenient
    # "--config functionRelocDiffs=data_value",
]

if args.mode == "configure":
    # Write build.ninja and objdiff.json
    generate_build(config)
elif args.mode == "progress":
    # Print progress information
    calculate_progress(config)
else:
    sys.exit("Unknown mode: " + args.mode)
