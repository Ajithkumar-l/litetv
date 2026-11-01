#!/usr/bin/env python3
"""Android TV optimizer: connect, analyze, backup, review bloat, build, install, test, rollback. Cross-platform."""
import subprocess, sys, os, shutil, platform, json, re, pathlib, datetime, time
ROOT = pathlib.Path(__file__).parent.resolve(); BK = ROOT / "backups"; BK.mkdir(exist_ok=True)
PROJ = ROOT / "LiteTVLauncher"; PKG = "com.lite.tvlauncher"; ACT = PKG + "/.MainActivity"
SERIAL_FILE = BK / "serial.txt"; STATE = BK / "state.json"
PROTECT = ("android", "com.android.systemui", "com.android.providers.", "com.android.shell", "com.android.packageinstaller",
    "com.google.android.packageinstaller", "com.android.inputmethod", "com.google.android.gms", "com.google.android.gsf",
    "com.android.vending", "com.google.android.tv.", "com.android.tv", "com.android.settings", "com.android.bluetooth",
    "com.android.networkstack", "com.android.permissioncontroller", "com.android.keychain", "com.android.certinstaller",
    "com.android.location", "com.android.webview", "com.google.android.webview", "com.android.documentsui",
    "com.android.externalstorage", "com.android.inputdevices", "com.google.android.inputmethod", PKG)
HINT = re.compile(r"recommend|promo|retaildemo|demo|sponsor|advert|\.ads|feedback|bugreport", re.I)

def find_adb():
    p = shutil.which("adb")
    if p: return p
    for c in ("~/Library/Android/sdk/platform-tools/adb", "~/Android/Sdk/platform-tools/adb",
              os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")):
        c = os.path.expanduser(c)
        if os.path.exists(c): return c
    hint = {"Windows": "winget install Google.PlatformTools", "Darwin": "brew install android-platform-tools",
            "Linux": "sudo apt install adb   (or your distro's package)"}.get(platform.system(), "")
    sys.exit(f"ADB not found ({platform.system()}). Install with:  {hint}")
ADB = find_adb() if "--nocheck" not in sys.argv else "adb"

def serial(): return SERIAL_FILE.read_text().strip() if SERIAL_FILE.exists() else None
def adb(*a, timeout=180):
    glob = a and a[0] in ("connect", "devices", "pair", "mdns", "disconnect")
    cmd = [ADB] + (["-s", serial()] if serial() and not glob else []) + list(a)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()
def sh(c): return adb("shell", c)
def ask(q): return input(q + " [y/N] ").strip().lower() == "y"
def load(): return json.loads(STATE.read_text()) if STATE.exists() else {"disabled": []}
def save(st): STATE.write_text(json.dumps(st))

def connect(ip=None):
    print("Laptop OS:", platform.system(), "| adb:", ADB)
    if not ip:
        print("Looking for TVs (mDNS)..."); print(adb("mdns", "services") or "(none advertised)")
        print("Neighbours on your network (arp):"); print(subprocess.run(["arp", "-a"], capture_output=True, text=True).stdout[:1500])
        ip = input("TV IP (TV Settings > Network shows it): ").strip()
    if ":" not in ip: ip += ":5555"
    print(adb("connect", ip))
    m = re.search(re.escape(ip) + r"\s+(\w+)", adb("devices")); state = m.group(1) if m else None
    if state == "unauthorized": sys.exit("Accept the 'Allow USB debugging?' prompt on the TV (tick 'Always allow'), then rerun.")
    if state != "device":
        sys.exit("Not connected. On the TV: Settings > Device Preferences > About > tap 'Build' 7 times, then Developer options >\n"
                 "enable USB/ADB debugging (and 'Network debugging' if present). On Android 11+ TVs use Wireless debugging >\n"
                 "'Pair device with pairing code', run  adb pair <ip:pairport>  then rerun with the connect port (ip:port).\n"
                 "Very old TVs may need a one-time USB cable:  adb tcpip 5555")
    SERIAL_FILE.write_text(ip)
    print("Verified:", sh("echo ok"), "| model:", sh("getprop ro.product.model"), "| Android", sh("getprop ro.build.version.release"), "(SDK", sh("getprop ro.build.version.sdk") + ")")

def analyze():
    d = BK / datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); d.mkdir()
    items = {"props.txt": "getprop", "meminfo.txt": "cat /proc/meminfo", "cpuinfo.txt": "cat /proc/cpuinfo", "storage.txt": "df",
             "packages_all.txt": "pm list packages -f -u", "packages_system.txt": "pm list packages -s", "packages_user.txt": "pm list packages -3",
             "packages_disabled.txt": "pm list packages -d", "processes.txt": "ps -A || ps", "meminfo_apps.txt": "dumpsys meminfo",
             "services.txt": "dumpsys activity services", "settings_global.txt": "settings list global",
             "settings_secure.txt": "settings list secure", "settings_system.txt": "settings list system",
             "home.txt": "cmd package resolve-activity --brief -c android.intent.category.HOME -a android.intent.action.MAIN"}
    for f, c in items.items(): (d / f).write_text(sh(c))
    home = (d / "home.txt").read_text().strip().splitlines(); st = load()
    if home and "/" in home[-1] and "original_home" not in st:
        st["original_home"] = home[-1].strip(); save(st)
    mem = (d / "meminfo.txt").read_text()
    g = lambda k: int(re.search(k + r":\s+(\d+)", mem).group(1)) // 1024
    print(f"Backup saved: {d}\nRAM total {g('MemTotal')} MB, available {g('MemAvailable') if 'MemAvailable' in mem else g('MemFree')} MB")
    print("Storage (/data):", [l for l in (d / "storage.txt").read_text().splitlines() if "/data" in l][:2])
    print("CPU cores:", (d / "cpuinfo.txt").read_text().count("processor\t"), "| Home launcher:", home[-1] if home else "unknown")
    print("User apps:", len((d / "packages_user.txt").read_text().splitlines()), "| System pkgs:", len((d / "packages_system.txt").read_text().splitlines()))
    print("Top memory (full list in meminfo_apps.txt):"); print("\n".join(sh("dumpsys meminfo").splitlines()[:14]))

def protected(p): return any(p == x or p.startswith(x if x.endswith(".") else x + ".") for x in PROTECT)

def bloat():
    sysp = {l[8:] for l in sh("pm list packages -s").splitlines() if l.startswith("package:")}
    dis = {l[8:] for l in sh("pm list packages -d").splitlines() if l.startswith("package:")}
    st = load(); home = st.get("original_home", "").split("/")[0]
    cands = sorted(p for p in sysp - dis if HINT.search(p) and not protected(p) and p != home)
    if not cands: return print("No obvious bloat candidates found. (Nothing changed.)")
    print("Candidates (reversible via pm enable). You approve each one:")
    for p in cands:
        if ask(f"Disable {p}?"):
            print(sh(f"pm disable-user --user 0 {p}")); st["disabled"].append(p); save(st)
    print("Undo any time:  python3 tvtool.py rollback")

def build():
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk: (PROJ / "local.properties").write_text("sdk.dir=" + sdk.replace("\\", "/") + "\n")
    gw = PROJ / ("gradlew.bat" if platform.system() == "Windows" else "gradlew")
    tool = str(gw) if gw.exists() else shutil.which("gradle")
    if not tool: return print("No Gradle found. Open LiteTVLauncher/ in Android Studio > Build > Build APK(s), then:  python3 tvtool.py install")
    r = subprocess.run([tool, "assembleDebug"], cwd=PROJ); print("Build", "OK" if r.returncode == 0 else "FAILED")

def apk(): return PROJ / "app/build/outputs/apk/debug/app-debug.apk"

def install():
    if not apk().exists(): sys.exit("APK not found. Build first (Android Studio: Build > Build APK(s)).")
    print(adb("install", "-r", str(apk())))

def test():
    out = sh(f"am start -W -n {ACT}"); print(out)
    m = re.search(r"TotalTime:\s*(\d+)", out); print("Start time ms:", m.group(1) if m else "n/a")
    for k in (22, 22, 20, 21, 19): sh(f"input keyevent {k}")   # D-pad right,right,down,left,up
    sh("input keyevent 23"); time.sleep(2); sh("input keyevent 3"); time.sleep(1)  # OK (opens focused app), then Home
    print("Process alive:", PKG in sh("ps -A | grep tvlauncher || ps | grep tvlauncher") or "tvlauncher" in sh("ps | grep tvlauncher"))
    print("\n".join(l for l in sh(f"dumpsys meminfo {PKG}").splitlines() if "TOTAL" in l or "Java Heap" in l))
    print("Crash log entries:", sh(f"logcat -d -b crash | grep -c {PKG}"))
    print("TV's own RAM figures (compare to launcher bar):", sh("grep -E 'MemTotal|MemAvailable' /proc/meminfo"))
    print("Visually confirm on the TV: clock, RAM bar, storage bar, Wi-Fi label, focus ring moving with the remote.")

def sethome():
    if not ask("Make Lite Launcher the default Home? (Original stays installed; rollback available)"): return
    print(sh(f"cmd package set-home-activity {ACT}") or "done")
    print("If that didn't work: press Home on the remote, choose Lite Launcher, then 'Always'.")

def rollback():
    st = load()
    for p in st.get("disabled", []): print("enable", p, sh(f"pm enable {p}"))
    st["disabled"] = []; save(st)
    oh = st.get("original_home")
    if oh: print("Restoring home:", oh, sh(f"cmd package set-home-activity {oh}"))
    if ask("Uninstall Lite Launcher too?"): print(adb("uninstall", PKG))
    print("If Home still opens the wrong launcher: TV Settings > Apps > Lite Launcher > Clear defaults.")

CMDS = {"analyze": analyze, "bloat": bloat, "build": build, "install": install, "test": test, "sethome": sethome, "rollback": rollback}
if __name__ == "__main__":
    a = sys.argv[1:] or ["help"]
    if a[0] == "connect": connect(a[1] if len(a) > 1 else None)
    elif a[0] == "all":
        connect(a[1] if len(a) > 1 else None); analyze(); bloat(); build(); install(); test(); sethome()
    elif a[0] in CMDS: CMDS[a[0]]()
    else: print("Usage: tvtool.py all <ip> | connect [ip] | analyze | bloat | build | install | test | sethome | rollback")
