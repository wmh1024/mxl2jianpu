# mxl2jianpu

把 OCR 出来的 MusicXML 变成**简谱 PDF** 和**简谱+五线谱对照 PDF**，并在转换前用**多模态模型对照印刷谱**把 OCR 的错误找出来。

面向的场景：拿到一份扫描谱（PDF）和它的 OMR 识别结果（`.mxl` / `.musicxml`）。
识别结果看着像谱，但小节经常对不上，直接转换只会得到一份错谱。
这个工具先诊断、再按需修复、然后渲染，最后和上一版逐小节比对、把改动标红。

## 这个工具假定你有视觉能力

流程的枢纽是「把 PDF 渲染成图片、逐小节与 OCR 结果对照」。所以：

- **必须有能读图的模型。** 纯文本模型跑这个流程，只会产出看起来合理、实际错误的谱子。
- **印刷谱是唯一权威。** OCR 结果不是待改进的草稿，而是待核对的证据。

工具在机制上限制了「私自修改」：任何对 OCR 的改动都必须带 `--evidence`，
写明第几页、看到什么。没有证据的改动会被拒绝执行，并写进 `changes.json`。

| 命令 | 作用 |
|---|---|
| `pages` | 把印刷谱每页渲染成图片，供模型查看 |
| `crop` | 放大裁剪某页的某个区域 |
| `diagnose` | 列出 OCR 的缺陷 |
| `review-bars` | 按「差多少拍」把可疑小节分组 |
| `repair` / `build` | 带证据修复并渲染 |
| `review` | 两版比对，改动处标红 |

## 依赖

| 工具 | 用途 | 查找顺序 |
|---|---|---|
| [LilyPond](https://lilypond.org/) 2.24+ | 排版成 PDF | `$MXL2JP_LILYPOND` → `PATH` → WinGet / Program Files |
| [jianpu-ly](https://github.com/ssb22/jianpu-ly) | 简谱预处理 | 已内置于 `vendor/` |
| Python 3.10+ | 运行本工具 | — |
| `pymupdf` 或 `pypdfium2` | 渲染页面图片给模型看 | `pip install pymupdf` |

```powershell
python mxl2jianpu/run.py tools     # 确认 lilypond 和 jianpu-ly 都找到了
```

下文命令都以 `python mxl2jianpu/run.py <命令>` 的形式给出。`run.py` 会自动处理
包路径，从任意目录执行都不需要设置 `PYTHONPATH`。

如果更习惯模块方式，等价写法是先设路径再调用：

```powershell
$env:PYTHONPATH = "<repo>/mxl2jianpu"
python mxl2jianpu/run.py tools
```

## 流程

### 1. 先看谱

```powershell
python mxl2jianpu/run.py pages score.pdf -o look --dpi 200
```

在做任何判断之前先把谱看清楚：几页、每页几个系统、拍号和调号在哪些小节变、
有没有反复记号、标题栏写的是什么。细节看不清就裁剪放大：

```powershell
python mxl2jianpu/run.py crop score.pdf -p 2 --box 0.05,0.42,0.55,0.52 -o look/p2-m17.png
```

`--box` 是相对页面的比例 `x0,y0,x1,y1`，从左上角量起。

### 2. 问工具哪里可能错了

```powershell
python mxl2jianpu/run.py diagnose score.mxl
```

输出按类别归并的问题清单。能查出来的都是文件本身能证明的：

| 类别 | 含义 |
|---|---|
| `bar-length` | 某个声部的小节长度对不上拍号（最常见） |
| `duration-type` | `<duration>` 和 `<type>` 互相矛盾 |
| `divisions-change` | `<divisions>` 在曲中变化，时值不可跨段比较 |
| `duplicate-number` | 小节号重复 |
| `orphan-chord` | `<chord/>` 前面没有音符 |

再按「差多少拍」分组：

```powershell
python mxl2jianpu/run.py review-bars score.mxl
```

整段成批差同一拍数，通常是**拍号被识别错**；零星几个小节差一点，多半是漏了休止符。
但这只是线索，不是结论——要去谱面上确认。

### 3. 对照谱面确认

这一步**必须看图**，不能靠推断：OMR 把 6/8 认成 4/4 时，文件内部是完全自洽的，
任何文件层面的检查都发现不了，只有谱面能证明。

确认之后，把结论连同依据一起交给工具：

```powershell
--time-change 89=6/8 --evidence "time-signature=89=2=第 89 小节前印 6/8"
```

### 4. 修复

```powershell
python mxl2jianpu/run.py repair score.mxl -o fixed.musicxml `
    --title 曲名 --composer 作曲 --part 乐器 `
    --time-change 89=6/8 --evidence "time-signature=89=2=第 89 小节前印 6/8" `
    --time-change 140=4/4 --evidence "time-signature=140=3=第 141 小节回到 4/4" `
    --drop-tuplets 136 --evidence "tuplet=136=3=六个普通八分音符，无连音括号"
```

`--evidence` 的格式是 `类型=小节=页码=看到的什么`，每一条 override 都必须有一条对应的证据，
否则命令拒绝执行。改动会写进 `changes.json`。

修复顺序（`pipeline.apply_repairs`）：

1. 覆盖拍号
2. 去除指定小节的伪连音标记
3. **合并声部**（把内声部折叠成和弦音，保证不丢音）
4. **补齐/裁剪小节**
5. 统一 `<divisions>` 网格
6. 重编小节号
7. 写入元数据

第 3 步在第 4 步之前，这样补齐时看到的是最终单声部形态；第 4 步又会重跑一次，保证叠加和弦后仍然满拍。

### 5. 渲染

```powershell
python mxl2jianpu/run.py convert fixed.musicxml -o out --stem 曲名
```

得到 `曲名.jianpu.pdf`（纯简谱）和 `曲名.staff.pdf`（加 `WithStaff` 的对照版）。

### 6. 出对比版

```powershell
python mxl2jianpu/run.py review out_v2 out_v1 -o diff --label 已修正
```

逐小节比对两版的简谱文本，把不同的地方用**红色音符 + 红色粗小节线 + 红框标签**标出来。

或者一步到位：

```powershell
python mxl2jianpu/run.py build score.mxl -o out --stem 曲名 -v `
    --title 曲名 --composer 作曲 --part 乐器 `
    --time-change 89=6/8 --time-change 140=4/4 --drop-tuplets 136
```

## 校验

改完必须验证，两个脚本配合：

```powershell
python scripts\check_bars.py out\曲名.musicxml     # 每小节拍数是否满
python scripts\verify_pitches.py origin.mxl out\曲名.musicxml   # 音高是否丢了
```

`check_bars` 应报 `bars off: 0`，`verify_pitches` 应报 `every bar has the same pitches`。

转换失败时，`find_bad_bar.py` 用二分法定位第一个让 jianpu-ly 报错的小节：

```powershell
python scripts\find_bad_bar.py out\曲名.jianpu.txt
```

`debug_bar.py` 可以手算一小节每个 token 的时值：

```powershell
python scripts\debug_bar.py "q,63 q0. q0. 0 -"
```

## 比对的口径

`compare.changed_bars(old, new, notes_only=False)` 有两种口径：

- **默认**：逐 token 比对，能发现任何写法变化。
- **`notes_only=True`**：只看发声的音符，忽略休止符怎么写。

休止符有多种等价写法——`q0 q0`、`q0. q0. 0 -`、`q0 0` 可能都是同一段静默。
复核「有没有改错音」时用 `notes_only`，否则会被写法差异淹没；
检查「这一版到底动了哪些小节」时用默认口径。

## 几个容易踩的坑

**八度记号的方向由调号决定。** jianpu-ly 把 `1=X` 实现成 `\transpose c X`，起点是 `c`（C3）。
所以不带点的音符在 X 是 G/A/B 时实际发 X3，在 X 是 C/D/E/F 时发 X4。
`jianpu.jianpu.to_jianpu` 按这个规则选基准八度，换调时不用改配置。

**`<backup>` / `<forward>` 也要缩放。** 统一 `<divisions>` 时如果只改 `<note>`，
游标会在多声部小节里漂移，后面的音符全部错位。

**不能丢音。** 合并声部时，落在已发声位置上的音要变成和弦音；
直接把内声部删掉会让五线谱少音，而这在简谱上不容易看出来。

**六连音的 `<duration>` 是压缩值。** 去掉 `time-modification` 后必须按 `<type>` 重算时值，
否则音符仍按 1/3 拍发声。

**伪连音的小节号。** OMR 里的小节号可能和重排后的编号不同，`--drop-tuplets` 用**源文件**的编号。

## 目录

```
mxl2jianpu/
├── mxl2jp/
│   ├── musicxml.py    解析 .mxl/.musicxml，遍历小节
│   ├── diagnose.py    OMR 缺陷诊断
│   ├── repair.py      各类修复
│   ├── jianpu.py      固定调 → 首调，生成 jianpu-ly 输入
│   ├── rests.py       休止符合并
│   ├── render.py      调用 jianpu-ly / LilyPond
│   ├── compare.py     两版比对 + 红框标注
│   ├── pipeline.py    流程编排
│   └── cli.py         命令行
├── scripts/
│   ├── check_bars.py      每小节拍数检查
│   ├── verify_pitches.py  音高对比
│   ├── dump_bars.py       打印指定小节的原始事件
│   └── find_bad_bar.py    二分定位首个报错小节
└── docs/USAGE.md
```

## 许可

本工具代码由本项目提供。jianpu-ly 与 LilyPond 各自遵循其原有许可。
