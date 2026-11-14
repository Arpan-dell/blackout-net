"""Runs on the gimbal drone's companion computer (Raspberry Pi or Jetson) with node C on its USB port.

Sends every line node C prints to the control room laptop over the drones' Wi-Fi, one UDP packet per line,
and keeps trying when the USB lead is pulled out and put back.

  python3 hq_forward.py --serial /dev/ttyUSB0 --to 192.168.88.254:15100
  (on the laptop:  python tools/control_room.py --udp 15100 --gcs http://localhost:8765)

Needs pyserial:  sudo apt install python3-serial   (or pip install pyserial)
"""
import argparse, socket, sys, time


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--serial", default="/dev/ttyUSB0", help="node C's port on this computer")
    ap.add_argument("--to", required=True, metavar="HOST:PORT", help="the control room laptop")
    a = ap.parse_args()
    import serial
    host, port = a.to.rsplit(":", 1)
    dest, out = (host, int(port)), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Forwarding {a.serial} to {a.to}", flush=True)
    while True:
        try:
            s = serial.Serial()
            s.port, s.baudrate, s.timeout = a.serial, 115200, 1
            s.dtr = s.rts = False  # opening the port must not restart node C: its inbox is in memory only
            s.open()
            with s:
                while True:
                    line = s.readline()
                    if line:
                        try:
                            out.sendto(line.rstrip(b"\r\n"), dest)
                        except OSError as e:  # Wi-Fi dropped: lose this line, keep going
                            print(f"send failed: {e}", file=sys.stderr, flush=True)
        except Exception as e:  # unplugged: wait for it to come back
            print(f"{a.serial}: {e}; trying again in 2 s", file=sys.stderr, flush=True)
            time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
