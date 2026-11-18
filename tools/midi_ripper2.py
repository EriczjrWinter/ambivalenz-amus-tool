import mido
import time
import threading
import sys
import struct
import pickle

def find_loopmidi():
    for name in mido.get_input_names():
        if 'loopMIDI' in name:
            return name
    return None

port = find_loopmidi()
if not port:
    print("未找到 loopMIDI 端口，请确认 loopMIDI 已创建端口。")
    sys.exit(1)

print(f"使用端口: {port}")
print("开始录制。请切换到游戏并播放音乐。")
print("录制过程中，按 Ctrl+C 或按 Esc 键停止录制。")

messages = []
lock = threading.Lock()
stop_event = threading.Event()

def callback(msg):
    now_ns = time.perf_counter_ns()
    with lock:
        messages.append((now_ns, msg))

# 启动 Esc 键监听线程（如果安装了 keyboard 库）
try:
    import keyboard
    def wait_for_esc():
        keyboard.wait('esc')
        stop_event.set()
    threading.Thread(target=wait_for_esc, daemon=True).start()
    print("按 Esc 键也可停止。")
except ImportError:
    print("未安装 keyboard 库，只能使用 Ctrl+C 停止。")

start_time = time.time()
print_interval = 0.5
last_print = start_time

with mido.open_input(port, callback=callback) as inport:
    try:
        while not stop_event.is_set():
            now = time.time()
            elapsed = now - start_time
            # 每 0.5 秒更新一次显示
            if now - last_print >= print_interval:
                with lock:
                    msg_count = len(messages)
                # 用 \r 覆盖同一行
                sys.stdout.write(f"\r已录制: {elapsed:.1f} 秒，捕获 {msg_count} 条消息")
                sys.stdout.flush()
                last_print = now
            time.sleep(0.1)   # 保持低 CPU 占用
    except KeyboardInterrupt:
        print("\n检测到 Ctrl+C，停止录制。")

print("\n停止录制，正在处理...")

if not messages:
    print("没有录制到任何消息。")
    sys.exit(1)

first_ns = messages[0][0]
last_ns = messages[-1][0]
real_duration = (last_ns - first_ns) / 1e9
print(f"收到 {len(messages)} 条消息，实际录制时长 {real_duration:.3f} 秒")

# 保存原始消息
with open('raw_messages.pkl', 'wb') as f:
    pickle.dump(messages, f)
print("原始消息已保存为 raw_messages.pkl")

# 生成 MIDI（可在这里修改 BPM）
BPM = 120   # 如果播放速度不对，可以修改此值重新生成
TPB = 480
tempo_us = int(60 * 1e6 / BPM)
ticks_per_ms = (TPB * 1000) / tempo_us

track_data = bytearray()
# 添加 set_tempo 事件
tempo_bytes = tempo_us.to_bytes(3, 'big')
track_data += b'\x00\xFF\x51\x03' + tempo_bytes

accepted_types = {'note_on', 'note_off', 'control_change', 'program_change', 'pitchwheel'}
last_ts_ns = first_ns
gaps = []

for ts_ns, msg in messages:
    if msg.type not in accepted_types:
        continue

    delta_ms = (ts_ns - last_ts_ns) / 1e6
    last_ts_ns = ts_ns

    # 不再钳制。异常的间隔单独记下来，事后人工判断（通常是切窗口导致游戏被限速）
    if delta_ms >= 200:
        gaps.append(((ts_ns - first_ns) / 1e6, delta_ms))

    delta_ticks = int(round(delta_ms * ticks_per_ms))
    if delta_ticks < 0:
        delta_ticks = 0

    # 写入变长 delta
    while True:
        b = delta_ticks & 0x7F
        delta_ticks >>= 7
        if delta_ticks:
            track_data.append(b | 0x80)
        else:
            track_data.append(b)
            break

    track_data.extend(msg.bytes())

# 添加轨道结束
track_data += b'\x00\xFF\x2F\x00'

# 构建完整 MIDI 文件
midi = bytearray()
midi += b'MThd' + struct.pack('>IHHH', 6, 0, 1, TPB)
midi += b'MTrk' + struct.pack('>I', len(track_data)) + track_data

output_filename = f'recorded_{BPM}bpm.mid'
with open(output_filename, 'wb') as f:
    f.write(midi)

print(f"MIDI 已保存为 {output_filename}，BPM={BPM}")
print("（按 毫秒→tick 固定换算，所以播放时长就是真实录制时长，不需要再校正 BPM）")

# 统计：每通道的事件数，方便和别处的解码结果对照
import collections
cnt = collections.Counter()
for _, m in messages:
    if m.type == 'note_on' and m.velocity > 0:
        cnt[f'ch{m.channel}:note'] += 1
    elif m.type == 'program_change':
        cnt[f'ch{m.channel}:prog={m.program}'] += 1
print("\n每通道统计：")
for k in sorted(cnt):
    print(f"  {k:20s} {cnt[k]}")

if gaps:
    print(f"\n⚠ 检测到 {len(gaps)} 处 >=200ms 的异常间隔（可能影响时间轴）：")
    for t, d in gaps[:20]:
        print(f"   @{t:9.1f} ms  间隔 {d:8.1f} ms")
    print("   多半是切窗口导致游戏被限速；建议保持游戏前台重录。")
else:
    print("\n未检测到异常间隔。")