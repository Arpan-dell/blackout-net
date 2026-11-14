"""Make Arduino IDE sketches from the PlatformIO firmware: one folder per node, with the node already chosen.

  python tools/make_arduino_sketch.py            phase 1 (firmware/)  -> arduino/blackout_node_A, _B, _C
  python tools/make_arduino_sketch.py --phase 2  phase 2 (firmware-phase2/)

Then in the Arduino IDE: File > Open > arduino/blackout_node_A/blackout_node_A.ino, and upload.
Run it again after any change to the firmware: the sketches are copies (the arduino/ folder is not in git).
"""
import argparse, os, re, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make(phase, out):
    src = os.path.join(ROOT, "firmware" if phase == 1 else "firmware-phase2")
    with open(os.path.join(src, "platformio.ini"), encoding="utf-8") as f:
        ini = f.read()
    made = []
    for letter in "ABC":
        flags = re.search(rf"\[env:node_{letter.lower()}\]\s*build_flags\s*=\s*(.*)", ini)
        defines = re.findall(r"-D(\w+)=(\S+)", flags[1]) if flags else [("NODE_ID", str(ord(letter) - 64))]
        name = f"blackout_node_{letter}"
        folder = os.path.join(out, name)
        os.makedirs(folder, exist_ok=True)
        shutil.copy(os.path.join(src, "src", "main.cpp"), folder)
        shutil.copy(os.path.join(src, "src", "page.h"), folder)
        with open(os.path.join(src, "include", "config.h"), encoding="utf-8") as f:
            config = f.read()
        head = (f"// Node {letter}: these were build flags in platformio.ini (made by tools/make_arduino_sketch.py).\n"
                + "".join(f"#define {k} {v}\n" for k, v in defines))
        with open(os.path.join(folder, "config.h"), "w", encoding="utf-8") as f:
            f.write(config.replace("#pragma once\n", "#pragma once\n" + head, 1))
        with open(os.path.join(folder, f"{name}.ino"), "w", encoding="utf-8") as f:
            f.write(f"// BLACKOUT NET node {letter}, phase {phase}. The program is in main.cpp; settings in config.h.\n"
                    f"// Board: ESP32 Dev Module. Libraries: RadioLib 6.6.0, ArduinoJson 7.2.1.\n")
        made.append(folder)
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase", type=int, choices=(1, 2), default=1)
    ap.add_argument("--out", default=os.path.join(ROOT, "arduino"))
    a = ap.parse_args()
    for folder in make(a.phase, a.out):
        print("made", folder)
