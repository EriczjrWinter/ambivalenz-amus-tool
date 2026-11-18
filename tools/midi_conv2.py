import pickle
import sys
import os
import argparse
from mido import MidiFile, MidiTrack, Message, MetaMessage

# 二律背反各曲的引擎 tempo 值（从游戏音色表 / 解析结果里读出来的）
# 实际四分音符 BPM = tempo * 1.1
SONG_TEMPO = {
    1: 110, 2: 115, 3: 125, 4: 115, 5: 120, 6: 135, 7: 120, 8: 130,
    9: 118, 10: 140, 11: 125, 12: 100, 13: 100, 14: 110, 15: 115,
    16: 105, 17: 120, 18: 110, 19: 120, 20: 110, 21: 110,
}
TEMPO_TO_BPM = 1.1


def find_song_start(messages, window_ms=250, min_programs=4):
    """找最后一处「开曲标记」——引擎开曲时会给多条通道集中发 program change。

    先把 program change 按时间聚成簇（间隔 > window_ms 就另起一簇），
    再取最后一个「含 >= min_programs 个 PC」的簇的**第一个**索引。
    返回 0 表示没找到可裁的位置。
    """
    window_ns = window_ms * 1_000_000
    clusters = []
    last_t = None
    for i, (t_ns, m) in enumerate(messages):
        if m.type != 'program_change':
            continue
        if clusters and last_t is not None and t_ns - last_t <= window_ns:
            clusters[-1].append(i)
        else:
            clusters.append([i])
        last_t = t_ns
    good = [c for c in clusters if len(c) >= min_programs]
    if not good:
        return 0
    if len(good) >= 2:
        return good[-1][0]
    # 只有一簇：如果它不在开头，前面那些就是菜单 BGM
    return good[0][0] if good[0][0] > 0 else 0


def trim_to_last_song(messages, window_ms=250, min_programs=4):
    """砍掉最后一处开曲标记之前的内容（菜单 BGM 之类）。"""
    start = find_song_start(messages, window_ms, min_programs)
    if start <= 0:
        print('没有找到第二个「开曲标记」，保留全部内容。')
        return messages
    cut_ms = (messages[start][0] - messages[0][0]) / 1e6
    print(f'检测到开曲标记 @ {cut_ms:.1f} ms，裁掉前面 {start} 条消息（菜单 BGM）')
    return messages[start:]


def convert(messages, out_path, bpm=120, tpb=480):
    """把捕获的原始消息写成 SMF。

    关键点：按「毫秒 → tick」固定换算，所以得到的文件播放出来就是真实录制时长。
    不需要、也不应该再用总时长做 BPM 补偿——那会把中间有停顿的录音整体拉歪。
    """
    if not messages:
        print('没有消息')
        return None

    tempo_us = int(60 * 1e6 / bpm)
    ticks_per_ms = (tpb * 1000) / tempo_us

    mid = MidiFile(ticks_per_beat=tpb)
    track = MidiTrack()
    mid.tracks.append(track)
    track.append(MetaMessage('set_tempo', tempo=tempo_us, time=0))

    accepted = {'note_on', 'note_off', 'control_change',
                'program_change', 'pitchwheel', 'aftertouch', 'polytouch'}
    t0 = messages[0][0]
    last = t0
    n = 0
    for t_ns, msg in messages:
        if msg.type not in accepted:
            continue
        delta_ms = (t_ns - last) / 1e6
        last = t_ns
        delta_tick = max(0, int(round(delta_ms * ticks_per_ms)))
        track.append(msg.copy(time=delta_tick))
        n += 1

    track.append(MetaMessage('end_of_track', time=0))
    mid.save(out_path)

    dur = (messages[-1][0] - t0) / 1e9
    print(f'写入 {n} 条事件 → {out_path}')
    print(f'录制时长 {dur:.3f} 秒（BPM={bpm}，仅影响网格，不影响播放速度）')
    return dur


def main():
    ap = argparse.ArgumentParser(
        description='把 raw_messages.pkl 转成 MIDI（不做 BPM 自动校正）')
    ap.add_argument('raw', help='raw_messages.pkl')
    ap.add_argument('out', help='输出 .mid')
    ap.add_argument('--bpm', type=float, default=120, help='网格 BPM，默认 120')
    ap.add_argument('--song', type=int, help='曲号 1-21，用该曲已知的实际速度')
    ap.add_argument('--trim', action='store_true',
                    help='自动裁掉最后一处开曲标记之前的内容（应付鉴赏菜单 BGM）')
    a = ap.parse_args()

    with open(a.raw, 'rb') as f:
        messages = pickle.load(f)

    if a.trim:
        messages = trim_to_last_song(messages)

    bpm = a.bpm
    if a.song:
        tel = SONG_TEMPO.get(a.song)
        if tel:
            bpm = round(tel * TEMPO_TO_BPM, 3)
            print(f'曲目 {a.song}: 引擎 tempo={tel} → BPM={bpm}')
        else:
            print(f'曲号 {a.song} 没有记录，回退到 {bpm}')

    convert(messages, a.out, bpm)


if __name__ == '__main__':
    main()
