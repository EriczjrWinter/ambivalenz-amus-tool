# -*- coding: utf-8 -*-
"""对照工具：把「实机录到的 MIDI 事件」和「我们解码出的 MIDI」按事件集合比较。

只比事件集合（通道 / program / 音高分布），不比较时间戳，
所以对录音抖动、切窗口限速这些都免疫——用来定位「缺哪条轨」最合适。

用法：
    python compare_capture.py raw_messages.pkl  "01 オープニング.mid"
    python compare_capture.py 实机录制.mid      "10 街.mid"
"""
import sys
import struct
import pickle
import collections


# ---------------- 读 SMF ----------------
def _vlq(buf, i, end):
    v = 0
    for _ in range(4):
        b = buf[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not (b & 0x80):
            return v, i
    raise ValueError('vlq')


def read_smf(path):
    """返回 (notes, progs)
    notes: list of (tick, ch, pitch)
    progs: dict ch -> list of (tick, program)
    """
    data = open(path, 'rb').read()
    if data[:4] != b'MThd':
        raise ValueError('不是 SMF')
    hlen, fmt, ntrk, div = struct.unpack_from('>IHHH', data, 4)
    pos = 8 + hlen
    notes, progs = [], collections.defaultdict(list)
    for _ in range(ntrk):
        if data[pos:pos + 4] != b'MTrk':
            break
        tlen = struct.unpack_from('>I', data, pos + 4)[0]
        i, end = pos + 8, pos + 8 + tlen
        tick, rs = 0, 0
        while i < end:
            d, i = _vlq(data, i, end)
            tick += d
            b = data[i]
            if b & 0x80:
                if b < 0xF0:
                    rs = b
                st = b
                i += 1
            else:
                st = rs
                if st == 0:
                    break
            if st == 0xFF:
                i += 1
                ln, i = _vlq(data, i, end)
                i += ln
                continue
            if st in (0xF0, 0xF7):
                ln, i = _vlq(data, i, end)
                i += ln
                continue
            if st >= 0xF8:
                continue
            k, ch = st & 0xF0, st & 0x0F
            if k in (0xC0, 0xD0):
                d1 = data[i]; i += 1
                if k == 0xC0:
                    progs[ch].append((tick, d1))
            else:
                d1, d2 = data[i], data[i + 1]; i += 2
                if k == 0x90 and d2 > 0:
                    notes.append((tick, ch, d1))
        pos = end
    return notes, progs


# ---------------- 读捕获 ----------------
def read_capture(path):
    if path.lower().endswith('.pkl'):
        with open(path, 'rb') as f:
            msgs = pickle.load(f)
        notes = []
        progs = collections.defaultdict(list)
        for t_ns, m in msgs:
            if m.type == 'note_on' and m.velocity > 0:
                notes.append((t_ns, m.channel, m.note))
            elif m.type == 'program_change':
                progs[m.channel].append((t_ns, m.program))
        return notes, progs
    return read_smf(path)


# ---------------- 比较 ----------------
def summarize(notes, progs):
    per_ch = collections.Counter(c for _, c, _ in notes)
    pitches = collections.defaultdict(collections.Counter)
    for _, c, p in notes:
        pitches[c][p] += 1
    last_prog = {}
    for c, lst in progs.items():
        if lst:
            lst.sort()
            last_prog[c] = sorted(set(p for _, p in lst))
    return per_ch, pitches, last_prog


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    cap_notes, cap_progs = read_capture(sys.argv[1])
    our_notes, our_progs = read_smf(sys.argv[2])

    cn, cp, cpr = summarize(cap_notes, cap_progs)
    on, op, opr = summarize(our_notes, our_progs)

    print('实机：%d 音符   |   我们：%d 音符' % (len(cap_notes), len(our_notes)))
    print()
    print('%-6s %-10s %-10s %s' % ('通道', '实机', '我们', '说明'))
    chans = sorted(set(cn) | set(on))
    for c in chans:
        a, b = cn.get(c, 0), on.get(c, 0)
        flag = ''
        if a and not b:
            flag = '<<< 实机有，我们完全没有'
        elif b and not a:
            flag = '>>> 我们有，实机没有'
        elif a and b and abs(a - b) / max(a, b) > 0.25:
            flag = '数量差异 %.0f%%' % (100.0 * (b - a) / max(a, b))
        print('%-6d %-10d %-10d %s' % (c, a, b, flag))

    print()
    print('--- program change ---')
    for c in chans:
        pa = cpr.get(c, [])
        pb = opr.get(c, [])
        if pa or pb:
            mark = '' if set(pa) == set(pb) else '  差异'
            print('ch%-3d 实机 %-18s 我们 %-18s%s' % (c, pa, pb, mark))

    print()
    print('--- 音高分布差异（只列缺失/多余，按出现次数） ---')
    for c in chans:
        a = cp.get(c, collections.Counter())
        b = op.get(c, collections.Counter())
        missing = [(p, n, b.get(p, 0)) for p, n in sorted(a.items()) if b.get(p, 0) == 0]
        extra = [(p, n, a.get(p, 0)) for p, n in sorted(b.items()) if a.get(p, 0) == 0]
        if missing or extra:
            print('ch%d:' % c)
            if missing:
                print('   实机有而我们没有的音高:', [(p, n) for p, n, _ in missing][:16])
            if extra:
                print('   我们有而实机没有的音高:', [(p, n) for p, n, _ in extra][:16])


if __name__ == '__main__':
    main()
