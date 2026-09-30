#!/usr/bin/env python3
"""Parse the Wireshark/USBPcap text dumps in tests/fixtures/v3/ into (dir, bytes) tuples."""
import re, sys

LINE = re.compile(
    r'^(?P<ep>\d+)\t(?P<dir>Out|In)\s+\(USB URB Function: (?P<fn>\d+)\)\t'
    r'(?P<dt>[\d.]+)\t(?P<len>\d+)\t(?P<hex>(?:[0-9a-f]{2} ?)+)', re.I)

def parse(path):
    out = []
    with open(path, errors='replace') as fh:
        for raw in fh:
            m = LINE.match(raw.rstrip('\n'))
            if not m:
                continue
            data = bytes.fromhex(m.group('hex').replace(' ', ''))
            out.append((m.group('dir'), float(m.group('dt')), data))
    return out

def trim(b):
    """Strip trailing zero padding for display."""
    i = len(b)
    while i > 0 and b[i-1] == 0:
        i -= 1
    return b[:i]

if __name__ == '__main__':
    for path in sys.argv[1:]:
        print(f'### {path}')
        for d, dt, b in parse(path):
            if d != 'Out':
                continue
            print('  %-4s %s' % (d, trim(b).hex(' ')))
