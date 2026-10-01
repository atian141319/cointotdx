"""Shift minute display labels only; exact UTC data and numeric bytes are untouched."""
from datetime import datetime, timedelta
import struct


def shift_minute_labels(data, offset_minutes):
    if len(data) % 32:
        raise ValueError('Minute file is not aligned to 32-byte records')
    if type(offset_minutes) is not int or not -840 <= offset_minutes <= 840:
        raise ValueError('Invalid display offset')
    output = bytearray(data)
    for index in range(0, len(data), 32):
        day, minute = struct.unpack_from('<HH', data, index)
        if minute >= 1440:
            raise ValueError('Invalid minute label')
        moment = datetime(day // 2048 + 2004, (day % 2048) // 100,
                          (day % 2048) % 100, minute // 60, minute % 60)
        shifted = moment + timedelta(minutes=offset_minutes)
        packed_date = (shifted.year - 2004) * 2048 + shifted.month * 100 + shifted.day
        if not 0 <= packed_date <= 65535:
            raise ValueError('Shifted date outside LC1/LC5 range')
        struct.pack_into('<HH', output, index, packed_date, shifted.hour * 60 + shifted.minute)
        if output[index + 4:index + 32] != data[index + 4:index + 32]:
            raise AssertionError('Numeric or tail fields changed')
    return bytes(output)
