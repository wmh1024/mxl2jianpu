# AGENT.md — 给 Agent 的操作手册

你是被要求把一份印刷简谱/五线谱变成**数字简谱 PDF** 的 Agent。这份文件告诉你：需要什么环境、用什么平台、按什么顺序做、以及哪些事绝对不能做。

先读这一页。然后加载技能 `.agents/skills/mxl2jianpu/SKILL.md`，那里有完整的判断依据。

---

## 1. 硬性前提：你必须能读图

这个任务的枢纽是**把印刷谱渲染成图片、逐小节和 OCR 结果对照**。

- 如果你**能**读取图片：按本文件继续。
- 如果你**不能**读取图片：停下来，直接告诉用户：

  > 这个任务需要多模态模型。我必须把 `score.pdf` 渲染成图片并逐小节核对 OCR 结果；
  > 我当前无法读取图像，继续做只会产出看起来合理但实际错误的谱子。
  > 请换成支持视觉的模型，或由人工完成核对。

  不要试图用纯文本「推断」谱面内容。OCR 把 6/8 认成 4/4 时文件内部完全自洽，只有看图才能发现。

---

## 2. 环境

### 平台

| 项 | 要求 |
|---|---|
| Agent 平台 | 任何能执行 shell 且支持视觉的 Agent。已验证：[DeepSeek Harness](https://github.com/deepseek-ai)（本仓库的 `.agents/skills/` 布局即为其技能目录约定） |
| 操作系统 | Windows / Linux / macOS 均可。工具本身跨平台，只有外部程序的查找路径与 Windows 相关 |
| 语言运行时 | **Python 3.10+**，需要能 `import` 本仓库的 `mxl2jianpu` 包 |

### 必须就绪的三样东西

在开始之前逐项确认。缺少任何一项都必须先装好，不要带着缺失往下走。

| 组件 | 作用 | 如何就绪 |
|---|---|---|
| **LilyPond 2.24+** | 把 LilyPond 源码排成 PDF | 唯一需要单独安装的外部程序。Windows `winget install LilyPond.LilyPond`；macOS `brew install lilypond`；Linux 用发行版包管理器 |
| **PDF 渲染库** | 把 PDF 转成图片给你看 | `pip install pymupdf`（或 `pypdfium2`） |
| **jianpu-ly** | 简谱预处理 | **已内置于** `mxl2jianpu/vendor/jianpu-ly/`，无需安装 |

`run.py` 会自动处理包路径，所以**不需要设置 PYTHONPATH**。所有命令统一这样调用：

```powershell
python mxl2jianpu/run.py tools      # 应打印 lilypond 与 jianpu-ly 的路径
```

`tools` 是环境自检：它把两个外部依赖的解析结果打印出来。
**如果它报错，先解决环境问题，不要绕开。**

可用的环境变量（仅在自动查找失败时需要）：

```powershell
$env:MXL2JP_LILYPOND = "C:\path\to\lilypond.exe"
$env:MXL2JP_JIANPULY  = "C:\path\to\jianpu-ly.py"
```

### 自检

`tools` 是最快的环境自检：它把两个外部依赖的解析结果打印出来。

```powershell
python mxl2jianpu/run.py tools
```

期望看到两行都有真实路径：

```
lilypond : C:\...\lilypond.exe
jianpu-ly: C:\...\jianpu-ly.exe   (或 vendor/jianpu-ly/jianpu-ly.py)
```

若 `lilypond` 显示 `None`，说明排版引擎没装好；若 `jianpu-ly` 显示 `None`，
说明 `vendor/` 目录缺失。**先解决，不要带着缺失往下走。**

再确认渲染链路能通（用一份最小简谱试排一次，不需要任何乐谱文件）：

```powershell
"1=D`n4/4`n1 2 3 4 | 5 6 7 1 |" > smoke.txt
python mxl2jianpu/scripts/smoke_test.py smoke.txt
```

预期末行 `SMOKE PASS`。这条命令只验证 jianpu-ly → LilyPond → PDF 这条链，
不涉及任何乐谱数据。


---

## 3. 你手上的两个输入

| 文件 | 地位 |
|---|---|
| `score.pdf`（印刷谱） | **唯一权威**。所有判断以它为准 |
| `score.mxl` / `.musicxml`（OCR 结果） | **待核对的证据**，一定存在错误，只是错在哪里未知 |

不要把 OCR 结果当成「待完善的草稿」去改进。它是别人给你的读数，你的工作是核对它，不是重写它。

---

## 4. 工作顺序

完整依据见 `SKILL.md`。这里是必须遵守的骨架：

### 第一步：看谱，先于一切判断

```powershell
python mxl2jianpu/run.py pages score.pdf -o look --dpi 200
```

看清楚了再往下走：几页、每页几个系统、拍号在哪些小节变、调号如何变、有无反复记号、标题栏写了什么。细节看不清就裁剪放大：

```powershell
python mxl2jianpu/run.py crop score.pdf -p 2 --box 0.05,0.42,0.55,0.52 -o look/p2.png --zoom 3
```

### 第二步：问工具哪里可疑

```powershell
python mxl2jianpu/run.py diagnose score.mxl
python mxl2jianpu/run.py review-bars score.mxl
```

工具列出的是**问题清单，不是答案**。它告诉你哪些小节对不上拍号，不告诉你应该改成什么。

### 第三步：到谱面上确认，逐组进行

对每一组可疑小节：裁剪对应页面 → 看清谱面 → 决定 OCR 是否正确。

确认之后再写 override。**没有看过图就不要写 override。**

### 第四步：带证据修复

```powershell
python mxl2jianpu/run.py build score.mxl -o out --stem 曲名 `
    --title 曲名 --composer 作曲 --part 乐器 `
    --time-change 89=6/8 --evidence "time-signature=89=2=第 89 小节前印 6/8" `
    --drop-tuplets 136   --evidence "tuplet=136=3=六个普通八分音符，无连音括号"
```

`--evidence 类型=小节=页码=你看到了什么`。每一条 override 都必须有对应证据，否则**命令会拒绝执行**。这是设计，不是障碍——不要试图绕过。

标题、作曲、乐器名同样来自谱面。谱面没有就留空，不要拿文件名当曲名。

### 第五步：双重校验

```powershell
python mxl2jianpu/scripts/check_bars.py out/曲名.musicxml
python mxl2jianpu/scripts/verify_pitches.py score.mxl out/曲名.musicxml
```

两个都必须干净：

```
bars off: 0 of N
every bar has the same pitches as the original.
```

它们会以不同方式失败，两者都要。拍数正确但丢了音的情况是存在的——五线谱少一个音，简谱看不出异常，只有音高检查会报。

### 第六步：成品与印刷谱并排看

打开 `out/曲名.staff.pdf` 和 `score.pdf`，逐页比对：拍号变化位置、八度点方向、和弦有没有丢音、标题栏文字。

这一步不能省。整体偏一个八度的错误在文本里看不出来，两页并排一眼就能看见。

### 如果存在上一版

```powershell
python mxl2jianpu/run.py review out_v2 out_v1 -o diff --label 已修正
```

---

## 5. 绝对不要做的事

| 禁止 | 原因 |
|---|---|
| 不看图就下结论 | 文件自洽的错误只有谱面能发现 |
| 为了让流程跑通而改数据 | 报错说明有问题，先查清楚是什么 |
| 编造标题、作曲、乐器 | 谱面没有就是没有 |
| 添加谱面上不存在的音符、记号 | 这是最严重的错误：产出看起来完美的假谱 |
| 绕过 `--evidence` 要求 | 无证据的修改等同猜测 |
| 静默跳过看不清的地方 | 必须列出来，说清楚哪一小节、为什么看不清 |

**看不清时的正确回答是「不确定」，不是「大概是」。**

---

## 6. 交付时怎么说

报告里必须包含这些数字，且来自实际输出：

```
原始谱 : score.pdf, N 页
OCR    : score.mxl, N 小节
修改   : N 处，均有 evidence（见 out/changes.json）
  - 拍号 89-140 -> 6/8      p.2 「第 89 小节前印 6/8」
  - 删除连音 136            p.3 「六个普通八分音符，无连音括号」
校验   : bars off 0 / N ; 音高差异 0 / N
未定   : 无（或逐条列出看不清的小节）
交付   : out/曲名.jianpu.pdf, out/曲名.staff.pdf, out/changes.json
```

只说「转换完成，PDF 已生成」而没有这两个校验数字、没有证据清单，等于没做完。

如果你没能看图，就直说。**没和印刷谱核对过的谱子不算完成，无论 PDF 多漂亮。**

---

## 7. 需要更多细节时

| 文件 | 内容 |
|---|---|
| `.agents/skills/mxl2jianpu/SKILL.md` | 完整流程、判断依据、每种异常的表现与处置 |
| `.agents/skills/mxl2jianpu/PROMPTS.md` | 可直接复用的提示词 |
| `mxl2jianpu/README.md` | 工具参考：每个命令、每个参数、每种报错 |
| `mxl2jianpu/docs/USAGE.md` | 一次完整的实操记录，含真实排错过程 |
