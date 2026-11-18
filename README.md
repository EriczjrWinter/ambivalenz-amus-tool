# ambivalenz-amus-tool

Alice Soft **System3** 引擎 BGM 数据 `AMUS.DAT` 的逆向与 MIDI 导出。
以 *AMBIVALENZ -二律背反-*（1995/1996）为对象。

**方法不是手写解析器**，而是在 [Unicorn](https://github.com/unicorn-engine/unicorn) 里
把游戏自己的 `system3.exe` 音乐引擎**真正跑起来**，hook `midiOutShortMsg` 抓取它发出的每一条消息。
所以产物是「引擎本来想表达的东西」，不是对文件格式的猜测。

> **日本語**
> 本プロジェクトは *AMBIVALENZ -二律背反-* の BGM を `AMUS.DAT` から MIDI に復元します。
> 手法は [Unicorn](https://github.com/unicorn-engine/unicorn) 上で**ゲーム本体の音楽エンジンを実際に動かし**、
> 送出される `midiOutShortMsg` をフックすること。したがって得られるのは「エンジンが意図した内容」であり、
> ファイル形式の推測ではありません。
>
> **English**
> This project converts *AMBIVALENZ*'s BGM from `AMUS.DAT` into MIDI.
> The approach is to **run the game's own music engine** under
> [Unicorn](https://github.com/unicorn-engine/unicorn) and hook every `midiOutShortMsg` it emits.
> What you get is what the engine intended — not a guess at the file format.

## 结果

21 首全部导出，验证情况：

| 对照物 | 结果 |
|---|---|
| 第 1 首 vs 实机录音 | 7303/7303 音符，音高直方图 0 差异，27/27 program change |
| 第 21 首 vs 实机录音 | 6 个通道 program 全对，音高分布 0 差异 |

## 这个格式劝退在哪

数据本身的复杂度不算高，真正的坑是**音色是七层间接**：

```
游戏 ID(哈希) → MDA 资源 → 曲号 → 256 字节块 → 9 字节记录 → 驱动 → 合成器
```

每一层的键都是**运行期才确定的**。静态看文件只能看到一堆字节；
只有让引擎跑起来，才知道「第 21 首会去取第 21 块」。

这个隔离层当年解决的是真问题：同一首歌要能跑在 9 种不同的 PC-98 声卡上。

## 文档

- **[docs/AMUS-FORMAT.md](docs/AMUS-FORMAT.md)** —— 完整格式记录
  （容器结构、内部字节码、时间轴、MDA 音色块、27 处踩坑）

## 结构

```
src/
  amus_emu.py       Unicorn 装载 PE、导入打桩、接管分配器/文件读取/线程
  amus_ticks.py     tick 边界挂钩、按速度精确累积时间
  amus_allsongs.py  批量导出（含 MDA 音色块提取、固定声部）
  smfio.py          极简 SMF 读写
  extract_mda.py    从 .rsrc 提取 MDA 资源
  exe_dis.py        capstone 反汇编辅助

tools/
  midi_ripper_thru.py  录制实机 MIDI（带转发，可边录边听）
  midi_conv2.py        pkl → MIDI（毫秒→tick 固定换算，可选按曲 tempo）
  compare_capture.py   实机 vs 解码，按事件集合对照

docs/
  AMUS-FORMAT.md
```

## 用法

```bash
pip install unicorn capstone

python src/extract_mda.py        # 从 system3.exe 提取 MDA 资源 → mda/*.bin
python src/amus_allsongs.py      # 21 首全导出，约 15 秒
python src/amus_allsongs.py 1    # 只跑第 1 首
```

## 验证自己的输出

真正有价值的对照物是**实机录音**。搭法：

```
游戏 → loopMIDI Port A → midi_ripper_thru.py → loopMIDI Port B → 音源
```

前者打时间戳，后者出声，所以**边录边听**。录完：

```bash
python tools/compare_capture.py raw_messages.pkl "21 アリスのテーマ.mid"
```

它按**事件集合**对照（通道 / program / 音高分布），对录音抖动免疫。
缺一条轨会直接指出来：

```
通道     实机         我们         说明
2      542        0          <<< 实机有，我们完全没有
```

## 需要自备

`system3.exe` —— **不随本仓库分发**。

## 限制

- 第 2–21 首截在 300 秒（它们是循环 BGM，引擎不会自然结束）
- 还原的是「引擎的意图」，不是「当年 OPNA 芯片的波形」。后者需要驱动在 I/O 端口上的寄存器写入

## 参考

- [alice-tools](https://github.com/nunuhara/alice-tools)
- [HOOT](https://www.dmpsoftplace.net/hoot/) —— 是 PC-98 **虚拟机**（跑真驱动），不是解码器
- [xsystem35](https://github.com/kichikuou/xsystem35-sdl2) —— System3.5+ 重写实现，
  经查不含 AMUS/MDA 处理
- ALSMIDI / ALSMDED（Nasty / teru）—— 1990 年代 Alice 社音乐的 MIDI 化工具，`MDA` 之名出典于此
