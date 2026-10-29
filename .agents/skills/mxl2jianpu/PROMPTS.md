# Prompts for the agent

Ready-made prompts for driving this skill. The first one is the whole job; the
others are for the steps you may need to re-run on their own.

These are written for an agent **with a vision model**. If the agent cannot see
images, it must say so and stop — see "When there is no vision" at the end.

---

## The job prompt

Give the agent the two files and this:

> 我在 `inputs/` 里给你两个文件：
> - `score.pdf` —— 印刷谱的扫描件，这是**唯一权威**；
> - `score.mxl` —— OCR 软件识别出来的 MusicXML，**一定是错的**，只是错在哪儿还不知道。
>
> 请用 mxl2jianpu 这个 skill 生成两份 PDF：纯简谱，以及简谱+五线谱对照。
>
> 要求：
> 1. **先看谱**。把 PDF 渲染成图片，看清楚拍号、调号、段落、标题栏。
> 2. **不要臆想**。OCR 和谱面不一致时以谱面为准；谱面看不清就说"不确定"，不要猜。
> 3. 每一处对 OCR 的修改都要给出 `--evidence`，写明第几页、看到什么。
> 4. 交付前必须两件事都成立：每小节拍数正确、音高与原始 MXL 一致。
> 5. 最后把成品 PDF 和 `changes.json` 的位置告诉我，并逐条说明你改了什么、依据是什么。
>
> 只交付你核对过的内容。看不清的部分列出来，不要悄悄跳过。

---

## Step prompts

### Look at the score

> 把 `score.pdf` 每一页渲染成图片（`pages` 命令，200 dpi），逐页看一遍并告诉我：
> 总共几页、每页几个谱表系统、拍号在哪些小节变、调号在哪些小节变、有没有反复记号、
> 标题栏写了什么（曲名、作曲、乐器）。不要读 MusicXML，只看谱面。

### Diagnose and group the problems

> 运行 `diagnose` 和 `review-bars`，把可疑小节按"差多少拍"分组列出来。
> 对每一组，告诉我你**打算看哪一页的哪个位置**来确认，先别下结论。

### Reconcile one group

> 现在确认第 89–140 小节这一组。裁剪第 2 页对应位置放大看，回答：
> 第 89 小节谱面上印的拍号是什么？第 141 小节是不是回到了 4/4？
> 依据是你在图上看到的什么？如果看不清，说看不清。

### Compare the result against the print

> 把 `out/曲名.staff.pdf` 和 `score.pdf` 并排看，逐页对比。重点检查：
> 拍号变化位置、八度点的方向是否与谱面音区一致、和弦有没有丢音、标题栏文字。
> 只报告你**确实看到**的差异，说明在第几页第几小节。

---

## Phrases that keep the agent honest

Paste these when an agent starts improvising:

- 你没有看谱面就下结论了。先渲染图片再看。
- 这条修改的 `--evidence` 里没有说明你看到了什么。补上，或者撤销这次修改。
- 谱面上没有的东西不要加。你看不到，就写"不确定"。
- 不要为了让工具跑通而改数据。工具报错说明有问题，先搞清楚是什么。
- 你改动的这一小节，依据在第几页？指给我看。

---

## When there is no vision

If the agent has no image capability, it must not attempt the reconciliation.
The correct response is:

> 这个任务需要能看图的模型：必须把 `score.pdf` 渲染成图片、逐小节与 OCR 结果比对。
> 我当前无法读取图像，只能做纯文本处理，那样会产生看起来合理但实际错误的谱子。
> 请换用支持视觉的模型，或由人工完成 OCR 与谱面的核对。

It can still help with the mechanical parts — `diagnose`, `check_bars`,
`verify_pitches` — as long as it is clear that no page comparison happened.

---

## What "done" sounds like

A good final report contains:

```
原始谱 : score.pdf, 4 页
OCR    : score.mxl, 186 小节
修改   : 3 处，均有 evidence
  - 拍号 89-140 -> 6/8      p.2 "第 89 小节前印 6/8"
  - 拍号 141    -> 4/4      p.3 "第 141 小节回到 4/4"
  - 删除连音 136            p.3 "六个普通八分音符，无连音括号"
校验   : bars off 0 / 186 ; 音高差异 0 / 186
未定   : 无
交付   : out/曲名.jianpu.pdf, out/曲名.staff.pdf, out/changes.json
```

A report that says "转换完成，PDF 已生成" without the two verification numbers
and without evidence lines is not a finished job.
