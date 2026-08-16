import argparse
import csv
import struct
import sys
import time

try:
    import serial
except ImportError:
    print("pyserial not installed:  pip install pyserial")
    sys.exit(1)

PACKET_FORMAT = "<HHHHHHHHHHHBBH"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
MAGIC = 0xA5C3

FIELDS = [
    "magic", "raw", "filtered", "level", "deviation", "noise_floor",
    "threshold_on", "threshold_off", "hold_remaining", "fmac_status",
    "adc_errors", "state", "confirm_count", "checksum",
]

STATE_NAMES = {0: "WAITING", 1: "CONFIRMING", 2: "ACTIVE", 3: "HOLDING"}


def checksum(payload):
    return sum(payload[:PACKET_SIZE - 2]) & 0xFFFF


def read_packets(port, baud):
    link = serial.Serial(port, baud, timeout=1.0)
    buffer = bytearray()

    while True:
        chunk = link.read(PACKET_SIZE)
        if not chunk:
            continue

        buffer.extend(chunk)

        while len(buffer) >= PACKET_SIZE:
            if buffer[0] != (MAGIC & 0xFF) or buffer[1] != (MAGIC >> 8):
                buffer.pop(0)
                continue

            frame = bytes(buffer[:PACKET_SIZE])
            values = struct.unpack(PACKET_FORMAT, frame)
            packet = dict(zip(FIELDS, values))

            if packet["checksum"] != checksum(frame):
                buffer.pop(0)
                continue

            del buffer[:PACKET_SIZE]
            yield packet


def run_console(port, baud, csv_path):
    writer = None
    handle = None

    if csv_path:
        handle = open(csv_path, "w", newline="")
        writer = csv.writer(handle)
        writer.writerow(["time"] + FIELDS[1:])

    started = time.time()
    counter = 0

    try:
        for packet in read_packets(port, baud):
            counter += 1
            elapsed = time.time() - started

            if writer:
                writer.writerow([round(elapsed, 3)] + [packet[name] for name in FIELDS[1:]])

            if counter % 10 == 0:
                print(
                    "t={:7.2f}  raw={:5d}  filt={:5d}  level={:5d}  dev={:5d}  "
                    "noise={:5d}  Ton={:5d}  Toff={:5d}  {:<10s} cnt={:2d} hold={:3d} "
                    "fmac=0x{:02X} adc_err={:d}".format(
                        elapsed, packet["raw"], packet["filtered"], packet["level"],
                        packet["deviation"], packet["noise_floor"], packet["threshold_on"],
                        packet["threshold_off"], STATE_NAMES.get(packet["state"], "?"),
                        packet["confirm_count"], packet["hold_remaining"],
                        packet["fmac_status"], packet["adc_errors"],
                    )
                )
    except KeyboardInterrupt:
        pass
    finally:
        if handle:
            handle.close()
            print("saved: {}".format(csv_path))


def run_plot(port, baud, window):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed:  pip install matplotlib")
        sys.exit(1)

    from collections import deque

    raw = deque(maxlen=window)
    filtered = deque(maxlen=window)
    level = deque(maxlen=window)
    threshold_on = deque(maxlen=window)
    threshold_off = deque(maxlen=window)
    deviation = deque(maxlen=window)
    state = deque(maxlen=window)

    plt.ion()
    figure, (top, bottom) = plt.subplots(2, 1, sharex=True, figsize=(11, 7))

    counter = 0
    for packet in read_packets(port, baud):
        raw.append(packet["raw"])
        filtered.append(packet["filtered"])
        level.append(packet["level"])
        threshold_on.append(packet["threshold_on"])
        threshold_off.append(packet["threshold_off"])
        deviation.append(packet["deviation"])
        state.append(packet["state"])

        counter += 1
        if counter % 10 != 0:
            continue

        top.clear()
        top.plot(raw, linewidth=0.7, alpha=0.45, label="raw")
        top.plot(filtered, linewidth=1.0, label="FMAC")
        top.plot(level, linewidth=1.4, label="level (EMA)")
        top.plot(threshold_on, linestyle="--", linewidth=0.9, label="T_on")
        top.plot(threshold_off, linestyle=":", linewidth=0.9, label="T_off")
        top.set_ylabel("Q1.15")
        top.legend(loc="upper right", fontsize=8)
        top.grid(alpha=0.3)

        bottom.clear()
        bottom.plot(deviation, linewidth=1.0, label="deviation")
        bottom.plot([value * 2000 for value in state], linewidth=1.4, label="state x2000")
        bottom.set_ylabel("stability / state")
        bottom.set_xlabel("samples (10 ms)")
        bottom.legend(loc="upper right", fontsize=8)
        bottom.grid(alpha=0.3)

        plt.pause(0.001)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--plot", action="store_true")
    parser.add_argument("--window", type=int, default=1000)
    args = parser.parse_args()

    if args.plot:
        run_plot(args.port, args.baud, args.window)
    else:
        run_console(args.port, args.baud, args.csv)


if __name__ == "__main__":
    main()
