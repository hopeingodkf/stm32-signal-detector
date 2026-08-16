import argparse
import os
import struct
import sys
from datetime import datetime

PACKET_FORMAT = "<HHHHHHHHHHHBBH"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

FIELDS = [
    "magic", "raw", "filtered", "level", "deviation", "noise_floor",
    "threshold_on", "threshold_off", "hold_remaining", "fmac_status",
    "adc_errors", "state", "confirm_count", "checksum",
]

CSV_COLUMNS = [
    "Time", "Tick", "State", "StateName", "Raw", "Filtered", "Level", "Level_V",
    "Deviation", "NoiseFloor", "T_on", "T_off", "Confirm", "Hold", "FMAC", "ADC_Err",
]

STATE_NAMES = ["WAITING", "CONFIRMING", "ACTIVE", "HOLDING"]

BIN_MAGIC = b"SDET"
BIN_HEADER_SIZE = 64
FULL_SCALE = 32760.0
VREF = 3.3


def read_header(blob):
    if len(blob) < BIN_HEADER_SIZE or blob[0:4] != BIN_MAGIC:
        raise ValueError("не схоже на запис детектора: немає мітки SDET")
    version, packet_size, started = struct.unpack_from("<HHI", blob, 4)
    session = blob[16:48].split(b"\x00")[0].decode("utf-8", "replace")
    return version, packet_size, started, session


def convert(source, target, sample_period_ms):
    blob = open(source, "rb").read()
    version, packet_size, started, session = read_header(blob)

    if packet_size != PACKET_SIZE:
        raise ValueError("розмір пакета {} не збігається з очікуваним {}".format(
            packet_size, PACKET_SIZE))

    body = blob[BIN_HEADER_SIZE:]
    total = len(body) // packet_size
    start_time = datetime.fromtimestamp(started)

    print("сесія      : {}".format(session))
    print("формат     : версія {}, пакет {} Б".format(version, packet_size))
    print("початок    : {}".format(start_time.strftime("%d.%m.%Y %H:%M:%S")))
    print("пакетів    : {}".format(total))
    print("тривалість : {:.1f} с".format(total * sample_period_ms / 1000.0))

    bad = 0
    with open(target, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(";".join(CSV_COLUMNS) + "\n")

        for index in range(total):
            frame = body[index * packet_size:(index + 1) * packet_size]
            values = struct.unpack(PACKET_FORMAT, frame)
            packet = dict(zip(FIELDS, values))

            if packet["checksum"] != (sum(frame[:packet_size - 2]) & 0xFFFF):
                bad += 1
                continue

            elapsed_ms = index * sample_period_ms
            stamp = start_time.timestamp() + elapsed_ms / 1000.0
            state = packet["state"] % 4
            volts = packet["level"] * VREF / FULL_SCALE

            row = [
                datetime.fromtimestamp(stamp).strftime("%H:%M:%S"),
                str(elapsed_ms),
                str(state),
                STATE_NAMES[state],
                str(packet["raw"]),
                str(packet["filtered"]),
                str(packet["level"]),
                "{:.3f}".format(volts).replace(".", ","),
                str(packet["deviation"]),
                str(packet["noise_floor"]),
                str(packet["threshold_on"]),
                str(packet["threshold_off"]),
                str(packet["confirm_count"]),
                str(packet["hold_remaining"]),
                str(packet["fmac_status"]),
                str(packet["adc_errors"]),
            ]
            handle.write(";".join(row) + "\n")

    print("пошкоджених: {}".format(bad))
    print("записано   : {}".format(target))


def main():
    parser = argparse.ArgumentParser(description="Конвертація .bin запису детектора у CSV")
    parser.add_argument("source")
    parser.add_argument("target", nargs="?", default=None)
    parser.add_argument("--period", type=int, default=10,
                        help="період відліку в мілісекундах (типово 10)")
    args = parser.parse_args()

    target = args.target or os.path.splitext(args.source)[0] + ".csv"

    try:
        convert(args.source, target, args.period)
    except Exception as error:
        print("помилка: {}".format(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
