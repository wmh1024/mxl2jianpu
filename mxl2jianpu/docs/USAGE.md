# 使用流程

一份完整的实际操作记录，从「一叠扫描谱」到「可交付的简谱 PDF」。
以《乐作欢歌》中阮分谱（4 页印刷谱 + OMR 导出的 `.mxl`）为实例。

## 准备

```powershell
python mxl2jianpu/run.py tools
```

确认输出里 `lilypond` 和 `jianpu-ly` 都有路径。缺失时设环境变量：

```powershell
$env:MXL2JP_LILYPOND = 'C:\path\to\lilypond.exe'
$env:MXL2JP_JIANPULY  = 'C:\path\to\jianpu-ly.py'
```

## 第 1 步：诊断

```powershell
python mxl2jianpu/run.py diagnose origin.mxl
```

本例输出：

```
bars      : 186
findings  : 76 (73 errors)

bar-length        72 bars: 14, 17, 17, 21, 21, 25, 34, 45, 45 ...
                  voice 1 covers 4.5 of 4 beats (over by 0.5)
divisions-change   3 bars: 44, 91, 144
                  <divisions> changed 4 -> 8; ...
duplicate-number   1 bars: 91
                  measure number 91 appears 2 times
```

`72 bars` 是关键信号：如果只是零星几处，多半是漏了休止符；
整段成批出现，说明**拍号被识别错了**。

## 第 2 步：查印刷谱定拍号

诊断只说哪些小节不对。打开原版 PDF 对照：

- 第 89 小节前印着 **6/8**，到第 141 小节才回到 4/4
- OMR 全程记作 4/4，所以 89–140 每小节都「少 1 拍」

于是得到两个覆盖点：

```powershell
--time-change 89=6/8 --time-change 140=4/4
```

同时发现第 137 小节（源编号 136）在印刷谱上是**普通八分音符**，
而 OMR 标了一个 6:4 六连音：

```powershell
--drop-tuplets 136
```

> 注意这里用的是**源文件编号** 136，不是重排后的 137。

## 第 3 步：修复

```powershell
python mxl2jianpu/run.py repair origin.mxl -o v1.musicxml `
    --title 乐作欢歌 --composer 吴耀 --part 中阮 `
    --time-change 89=6/8 --time-change 140=4/4 --drop-tuplets 136
```

输出会逐条列出改动：

```
m53 v1: 1.625 -> 1.5 (no note value for the original)
m17: 2 voices merged, 1 notes folded in
rewrote 1308 durations on a 96/quarter grid
rescaled 34 backup/forward gaps
renumbered 186 measures
```

## 第 4 步：双重校验

```powershell
python scripts\check_bars.py v1.musicxml
python scripts\verify_pitches.py origin.mxl v1.musicxml
```

两个都必须干净：

```
bars off: 0 of 186
every bar has the same pitches as the original.
```

**为什么两个都要跑。** 只查拍数会漏掉「音被吃掉」，
只查音高会漏掉「时值不对」。曾经出现过：拍数全对、PDF 也好看，
但 7 个小节的五线谱少了一个持续音——只有音高比对能发现。

## 第 5 步：渲染

```powershell
python mxl2jianpu/run.py convert v1.musicxml -o out --stem 乐作欢歌
```

```
text         out\乐作欢歌.jianpu.txt
jianpu_ly    out\乐作欢歌.jianpu.ly
jianpu_pdf   out\乐作欢歌.jianpu.pdf      ← 纯简谱
staff_ly     out\乐作欢歌.staff.ly
staff_pdf    out\乐作欢歌.staff.pdf       ← 简谱 + 五线谱
```

打开对照版，与原版 PDF 逐页比对。重点看三处：

1. 调号变化处（第 33、85 小节附近）的八度点方向
2. 多声部小节（第 17、53 小节）有没有少音
3. 整段音高有没有整体偏高/偏低一个八度

## 第 6 步：出对比版

改完一版后，和上一版比：

```powershell
python mxl2jianpu/run.py review out_v2 out_v1 -o diff --label 已修正
```

```
changed bars: 42
  17,21,33-52,85-96,137,149,153
  jianpu   diff\jianpu.marked.pdf
  staff    diff\staff.marked.pdf
```

被标记的小节有红色音符、红色粗小节线和红框标签。

## 一条命令跑完

```powershell
python mxl2jianpu/run.py build origin.mxl -o out_v2 --stem 乐作欢歌 -v `
    --title 乐作欢歌 --composer 吴耀 --part 中阮 `
    --time-change 89=6/8 --time-change 140=4/4 --drop-tuplets 136
```

## 出错时

**`Error: ... barcheck fail: note crosses barline`**
报的小节号往往是对的、内容看着也正常，真正的错误在前面。
用二分法定位：

```powershell
python scripts\find_bad_bar.py out\乐作欢歌.jianpu.txt
```

输出 `first failing bar: 148` 就是第一个出问题的小节。

**`Error: Unrecognised command 3&,6`**
和弦写法错了。jianpu-ly 用连写数字表示和弦（`3,6`），不是 `&`。

**`Error: Ambiguous octave marks`**
和弦里八度记号位置有歧义。把记号写到每个音旁边，
或让整组共享同一个八度。

**PDF 里数字整体偏一个八度**
调号对应的基准八度错了，见 `jianpu.jianpu.to_jianpu` 的说明。

## 检查清单

交付前逐条确认：

- [ ] `check_bars.py` 报 `bars off: 0`
- [ ] `verify_pitches.py` 报 `every bar has the same pitches`
- [ ] 两份 PDF 都渲染出来，页数正常
- [ ] 与原版 PDF 目视比对过调号变化处和多声部小节
- [ ] 标题、作曲、乐器名正确
