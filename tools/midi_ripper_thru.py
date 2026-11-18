import mido
import time
import threading
import sys
import struct
import pickle

# ---------------------------------------------------------------
# 用法：
#   python midi_ripper_thru.py [捕获端口关键字] [监听端口关键字]
# 例：
#   python midi_ripper_thru.py            # 自动挑 loopMIDI 端口
#   python midi_ripper_thru.py "1" "2"    # Port A=含"1"的，Port B=含"2"的
#
# 路由： 游戏 → Port A → 本脚本 → Port B → SC-VA（这样才听得见）
# 时间戳在收到消息的瞬间打，转发在其后，不影响录制精度。
# ---------------------------------------------------------------

def pick(kind, keyword=None, avoid=None):
    names = mido.get_input_names() if kind == 'in' else mido.get_output_names()
    cands = [n for n in names if 'loopMIDI' in n or 'LoopMIDI' in n]
    if keyword:
        cands = [n for n in cands if keyword in n]
    if avoid:
        cands = [n for n in cands if avoid not in n]
    return cands[0] if cands else None


in_name = pick('in', sys.argv[1] if len(sys.argv) > 1 else None)
if not in_name:
    print("没找到 loopMIDI 输入端口。请在 loopMIDI 里至少建两个端口。")
    print("现有输入端口:", mido.get_input_names())
    sys.exit(1)

out_name = pick('out', sys.argv[2] if len(sys.argv) > 2 else None, avoid=in_name)
if not out_name:
    print("没找到可用的转发端口（需要第二个 loopMIDI 端口给 SC-VA）。")
    print("现有输出端口:", mido.get_output_names())
    print("可以只录制不转发；或加参数指定端口名关键字。")
    sys.exit(1)

print(f"捕获端口: {in_name}")
print(f"转发端口: {out_name}   → 让 SC-VA 监听这个端口，就能边录边听")
print("按 Esc 或 Ctrl+C 停止。")

messages = []
lock = threading.Lock()
stop_event = threading.Event()


def on_message(msg):
    now_ns = time.perf_counter_ns()
    with lock:
        messages.append((now_ns, msg))


try:
    import keyboard
    threading.Thread(target=lambda: (keyboard.wait('esc'), stop_event.set()),
                     daemon=True).start()
except ImportError:
    print("（未装 keyboard 库，只能用 Ctrl+C 停止）")

start_time = time.time()
last_print = start_time

with mido.open_input(in_name, callback=on_message) as inport, \
        mido.open_output(out_name) as outport:

    # mido 的 callback 不能直接转发（会阻塞），用后台线程轮询一份快照转发
    def pump():
        sent = 0
        while not stop_event.is_set():
            with lock:
                batch = messages[sent:]
            if batch:
                sent += len(batch)
                for _, m in batch:
                    try:
                        outport.send(m)
                    except Exception:
                        pass
            time.sleep(0.001)

    threading.Thread(target=pump, daemon=True).start()

    try:
        while not stop_event.is_set():
            now = time.time()
            if now - last_print >= 0.5:
                with lock:
                    n = len(messages)
                sys.stdout.write(f"\r已录制 {now - start_time:6.1f} 秒，捕获 {n} 条消息")
                sys.stdout.flush()
                last_print = now
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n停止录制。")

print()
if not messages:
    print("没有捕获到任何消息。")
    sys.exit(1)

first_ns = messages[0][0]
last_ns = messages[-1][0]
dur = (last_ns - first_ns) / 1e9
print(f"共 {len(messages)} 条，时长 {dur:.3f} 秒")

# 统计：每通道的事件数（用来和我们的解码结果对照）
import collections
cnt = collections.Counter()
for _, m in messages:
    if m.type == 'note_on' and m.velocity > 0:
        cnt[f'ch{m.channel}:note'] += 1
    elif m.type == 'program_change':
        cnt[f'ch{m.channel}:prog={m.program}'] += 1
for k in sorted(cnt):
    print(f"  {k:20s} {cnt[k]}")

with open('raw_messages.pkl', 'wb') as f:
    pickle.dump(messages, f)
print("原始消息 → raw_messages.pkl")

# 同时存一份原始时间戳文本，方便外部工具核对
with open('raw_messages.txt', 'w', encoding='utf-8') as f:
    for t_ns, m in messages:
        f.write(f"{(t_ns - first_ns) / 1e6:10.3f}\t{m}\n")
print("时间戳文本 → raw_messages.txt")
