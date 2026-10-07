"""博客后处理：规范检查与文件保存。"""
from __future__ import annotations

import os
import re

from src.blog_rules import FORBIDDEN_PATTERNS

# 标题 CTR 痛点词（与 check_blog 第 10 项、prompts/blog_synthesis.md 第 16 条保持一致）
PAIN_WORD_RE = r"为什么|到底|坑|排查|失效|翻车|追问|面试|陷阱|误区|别再|慎用|拆解|崩溃"


def normalize_blog(blog_content: str) -> str:
    """修正 LLM 输出的常见格式问题（提示词已禁止，此处兜底）：

    1. frontmatter 前混入开场白/自述 → 丢弃 frontmatter 之前的所有内容
    2. frontmatter 被包裹在 ```yaml 代码块中 → 去掉围栏，还原为裸文本
    """
    text = blog_content.strip()
    match = re.search(
        r"(?:```(?:ya?ml)?[ \t]*\n)?---\n.*?\n---(?:[ \t]*\n```)?",
        text,
        re.DOTALL,
    )
    # 用 title:/tags: 校验匹配到的确实是 frontmatter，而非正文里的分隔线
    if not match or not re.search(r"^(title|tags|date):", match.group(0), re.MULTILINE):
        return text
    frontmatter = re.sub(r"^```(?:ya?ml)?[ \t]*\n|```\s*$", "", match.group(0)).strip()
    return (frontmatter + "\n\n" + text[match.end():].lstrip("\n")).rstrip() + "\n"


# 掘金（旧版 mermaid + 发布转义）标签字符映射：全角→半角或空格
_MERMAID_CHAR_MAP = str.maketrans({
    "，": " ", "、": " ", "。": " ", "；": " ", "：": ":",
    "（": " ", "）": " ", "·": " ", "－": "-", "—": "-", "…": "...",
    "“": "'", "”": "'", "‘": "'", "’": "'", "→": "-",
    # & 可被旧版解析，但发布时会被转义为 &amp;；@ 旧版解析失败
    "&": " ", "@": " ",
})


def fix_mermaid_quotes(blog_content: str) -> str:
    """掘金发布安全的 mermaid 清洗。

    两层坑（编辑态预览均正常，发布后挂掉）：
    1. 掘金发布管线把代码块内的 HTML 特殊字符转义（`"` → `&#34;、
       `<br/>` → `&lt;br/&gt;`、`&` → `&amp;`），线上渲染器不解码
    2. 掘金的旧版 mermaid 解析器不支持无引号标签中的全角标点
       （、，。：（）？ 等实测全部失败，mermaid.ink 等新版能解析——不可信）

    因此标签必须：无引号、单行、仅含 中文/字母/数字/空格 及少量半角符号。
    """
    safe = r'([^"\[\]\{\}\|#]+)'

    def _fix_block(match: re.Match) -> str:
        block = match.group(1)
        # 换行标记与引号
        block = re.sub(r"<br\s*/?>", " ", block)
        block = re.sub(r'\["' + safe + r'"\]', r"[\1]", block)
        block = re.sub(r'\{"' + safe + r'"\}', r"{\1}", block)
        block = re.sub(r'\|"' + safe + r'"\|', r"|\1|", block)
        # 全角标点等旧版解析器不认的字符
        block = block.translate(_MERMAID_CHAR_MAP)
        # 连续空格收敛
        block = re.sub(r"[ \t]{2,}", " ", block)
        return "```mermaid\n" + block + "```"

    return re.sub(r"```mermaid\n(.*?)```", _fix_block, blog_content, flags=re.DOTALL)


def _title_ctr_ok(title: str) -> bool:
    """标题 CTR 要素判定：数字、问号、痛点词至少命中两类。"""
    hits = (
        bool(re.search(r"\d", title)),
        bool(re.search(r"[?？]", title)),
        bool(re.search(PAIN_WORD_RE, title)),
    )
    return sum(hits) >= 2


def _title_ok(title: str) -> bool:
    """标题合规判定：CTR 要素（数字/问号/痛点词至少两类）且长度 12-40 字。"""
    return _title_ctr_ok(title) and 12 <= len(title) <= 40


def promote_ctr_title(blog_content: str) -> str:
    """title 不达标（CTR 要素缺失或长度越界）而某条候选达标时，换成第一条达标的候选。

    模型偶尔自选的 title 弱于它自己生成的候选（check_blog 第 10 项会告警），
    此处做确定性提升，避免整篇因标题丢分。候选列表保持原样作为后备。
    """
    title_m = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", blog_content, re.MULTILINE)
    if not title_m or _title_ok(title_m.group(1)):
        return blog_content
    cand_block_m = re.search(
        r"^title_candidates:\n((?:[ \t]+-.*\n?)+)", blog_content, re.MULTILINE
    )
    candidates = (
        [c.strip().strip("\"'") for c in re.findall(r"-\s*(.+)", cand_block_m.group(1))]
        if cand_block_m
        else []
    )
    promoted = next((c for c in candidates if _title_ok(c)), None)
    if promoted:
        return re.sub(
            r"^title:.*$",
            lambda _m: f"title: {promoted}",
            blog_content,
            count=1,
            flags=re.MULTILINE,
        )
    return blog_content


def check_blog(blog_content: str) -> dict:
    """检查博客内容是否符合 technical-blog-writing 规范。

    返回 {"score": int, "warnings": list[str]}。
    score: 满分 10，每违反一条规则扣 1 分，最低为 0。

    检查项：
        1. 是否有摘要段落（TL;DR 等）且 ≤100 字
        2. 是否有进一步阅读/写在最后类收尾段落
        3. 是否包含 FORBIDDEN_PATTERNS 中的禁用词
        4. 代码块是否标注语言类型
        5. 是否有 YAML frontmatter、标题 ≤40 字
        6. 流程/时序/架构类内容应配 mermaid 图表
        7. mermaid 语法兼容掘金旧版渲染器
        8. 段落节奏（单段 ≤300 字）
        9. 文末开放性互动问句
        10. 标题 CTR 要素（数字/问号/痛点词至少两类、≥12 字）
        11. 站外链接（掘金降权因素）
    """
    warnings: list[str] = []
    score = 10

    # 1. 检查摘要段落（形式不限：TL;DR / 太长不看版 / 一句话结论 / 结论先行 / 速览）
    #    摘要 = 标题后的第一个段落；同小节内的后续段落视为开场叙事，不计入
    summary_match = re.search(
        r"##\s*(?:TL;DR|太长不看|一句话结论|结论先行|速览|摘要)[^\n]*\n(.*?)(?=\n## |\n---\s*\n|\Z)",
        blog_content,
        re.DOTALL | re.IGNORECASE,
    )
    if summary_match:
        summary_first_para = summary_match.group(1).split("\n\n")[0]
    else:
        summary_first_para = None
    if summary_first_para is None:
        warnings.append("缺少摘要段落（TL;DR / 太长不看版 / 一句话结论等形式均可）")
        score -= 1
    else:
        summary_len = len(re.sub(r"\s", "", summary_first_para))
        if summary_len > 100:
            warnings.append(f"摘要过长：{summary_len} 字（要求 ≤ 100 字）")
            score -= 1

    # 2. 检查收尾段落（进一步阅读/参考/写在最后等形式均可）
    if not re.search(
        r"##\s*(?:进一步阅读|延伸阅读|Further Reading|参考|References|相关资源|写在最后|总结)",
        blog_content,
        re.IGNORECASE,
    ):
        warnings.append("缺少进一步阅读/参考/写在最后类收尾段落")
        score -= 1

    # 3. 检查禁用词（每发现一类扣 1 分）
    found_forbidden: set[str] = set()
    for pattern in FORBIDDEN_PATTERNS:
        matches = re.findall(pattern, blog_content, re.IGNORECASE)
        if matches:
            # 取匹配到的唯一值，避免重复
            found_forbidden.update(set(matches))
    if found_forbidden:
        warnings.append(f"包含禁用词: {', '.join(sorted(found_forbidden))}")
        score -= 1

    # 4. 检查代码块是否标注语言类型
    #    按行扫描围栏配对，只统计"开栏"（每个代码块的第 1 个 ```）是否带语言，
    #    避免把闭合围栏误判为未标注
    unlabeled = 0
    in_code = False
    for line in blog_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code:
                if not stripped[3:].strip():
                    unlabeled += 1
                in_code = True
            else:
                in_code = False
    if unlabeled:
        warnings.append(f"有 {unlabeled} 个代码块未标注语言类型（``` 后未跟语言名）")
        score -= 1

    # 5. 检查 YAML frontmatter（文件以 --- 开头）及标题长度（掘金截断约 40 字）
    if not re.match(r"^---\s*\n", blog_content):
        warnings.append("缺少 YAML frontmatter（文件应以 --- 开头）")
        score -= 1
    else:
        title_m = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", blog_content, re.MULTILINE)
        if title_m and len(title_m.group(1)) > 40:
            warnings.append(f"标题过长：{len(title_m.group(1))} 字（掘金建议 ≤ 40 字）")
            score -= 1

    # 6. 内容涉及流程/时序/架构/竞态时应配有 mermaid 图表
    flow_keywords = re.search(
        r"流程|时序|架构|竞态|状态机|生命周期|链路"
        r"|flow|sequence|architecture|lifecycle|race condition",
        blog_content,
        re.IGNORECASE,
    )
    has_mermaid = "```mermaid" in blog_content
    if flow_keywords and not has_mermaid:
        warnings.append("内容涉及流程/时序/架构但缺少 mermaid 图表")
        score -= 1

    # 7. mermaid 语法兼容掘金等旧版渲染器（仅检查 mermaid 块内部）
    mermaid_blocks = re.findall(r"```mermaid\n(.*?)```", blog_content, re.DOTALL)
    if mermaid_blocks:
        compat_issues: list[str] = []
        for block in mermaid_blocks:
            # subgraph 标题必须带引号（subgraph G1["标题"]），裸中文标题旧版解析失败
            for line in block.splitlines():
                s = line.strip()
                if (
                    s.startswith("subgraph ")
                    and "[" not in s
                    and any(ord(ch) > 127 for ch in s)
                ):
                    compat_issues.append("subgraph 标题未用 subgraph G1[\"标题\"] 形式")
                    break
            # 边标签必须用管道语法（A -->|"文字"| B），-- 文字 --> 兼容性差
            if re.search(r"--[^->\n][^-]*-->", block):
                compat_issues.append("边标签应使用 -->|\"文字\"| 管道语法")
            # 掘金发布会把 < > 转义，<br/> 等换行标记会变成 &lt;br/&gt; 导致挂掉
            if re.search(r"<br\b|<\s*/?\s*[a-z]+", block, re.IGNORECASE):
                compat_issues.append("标签含 HTML 标签（如 <br/>），应改为单行标签")
            # HTML 实体（源码层面引入或上游转义残留）
            if re.search(r"&#?\w+;", block):
                compat_issues.append("含 HTML 实体（如 &#34;），应使用无引号单行标签")
            # 标签字符白名单：全角标点等旧版解析器不认、&/@ 发布后挂
            labels = (
                re.findall(r"\[([^\]]*)\]", block)
                + re.findall(r"\{([^}]*)\}", block)
                + re.findall(r"\|([^|]*)\|", block)
            )
            whitelist = re.compile(r"[\u4e00-\u9fffA-Za-z0-9?!%+=\-_'*./: ]*")
            bad_chars = {ch for label in labels for ch in label if not whitelist.fullmatch(ch)}
            if bad_chars:
                compat_issues.append(f"标签含不兼容字符: {''.join(sorted(bad_chars))}")
        if compat_issues:
            warnings.append("mermaid 含掘金不兼容语法: " + "；".join(set(compat_issues)))
            score -= 1

    # 8. 阅读节奏：正文段落过长（掘金移动端长段落跳出率高）
    #    先整体剔除代码块（含空行的代码会被按空行切开，碎片误判为长段落）
    prose = re.sub(r"```.*?```", "", blog_content, flags=re.DOTALL)
    long_paras = [
        p for p in re.split(r"\n\s*\n", prose)
        if not p.lstrip().startswith(("#", "|", ">", "```", "-", "!"))
        and not p.startswith("---")
        and len(re.sub(r"\s", "", p)) > 300
    ]
    if long_paras:
        warnings.append(f"有 {len(long_paras)} 个段落超过 300 字，建议拆分")
        score -= 1

    # 9. 互动引导：文末（完整度评估之前的正文尾部）应有开放性问句
    #    问号不必在行尾（问题后可接自答引导），扫文末尾部 500 字即可
    # 结尾说明段小节标题 LLM 命名不稳定（内容完整度评估/自评、与原视频说法的差异说明），统一剥掉
    body_end = re.split(
        r"\n(?:#+\s*|\*\*)\s*(?:内容完整度|与原视频说法的差异说明)",
        blog_content,
    )[0].rstrip()
    # 说明段也可能没有小节标题，只以 --- 分隔线 + 有序列表出现
    parts = body_end.rsplit("\n---\n", 1)
    if len(parts) == 2 and re.match(r"\s*\d+\.", parts[1]):
        body_end = parts[0].rstrip()
    if not re.search(r"[?？]", body_end[-500:]):
        warnings.append("文末缺少开放性互动问题（引导评论）")
        score -= 1

    # 10. 标题 CTR 要素（推荐流点击率导向）：数字、问号、痛点词至少命中两类
    title_val = ""
    _title_m = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", blog_content, re.MULTILINE)
    if _title_m:
        title_val = _title_m.group(1)
    if title_val:
        if not _title_ctr_ok(title_val):
            warnings.append(
                "标题缺少 CTR 要素：数字/问号/痛点词（为什么、排查、失效等）至少命中两类"
            )
            score -= 1
        if 0 < len(title_val) < 12:
            warnings.append(f"标题过短：{len(title_val)} 字（信息量不足，建议 12-40 字）")
            score -= 1

    # 11. 站外链接（掘金对外链降权，资源应改为名称文字描述）
    #     只查正文（prose 已剔除代码块，代码里的 URL 是合理的）
    ext_urls = [
        u for u in re.findall(r"https?://[^\s)\]、，。；]+", prose) if "juejin.cn" not in u
    ]
    if ext_urls:
        warnings.append(
            f"含 {len(ext_urls)} 个站外链接（掘金对外链降权），建议改为资源名称文字描述"
        )
        score -= 1

    return {"score": max(0, score), "warnings": warnings}


# 掘金发布表单的分类（单选）：按 tags 推断，顺序即优先级
_JUEJIN_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("前端", ("前端", "React", "Vue", "JavaScript", "TypeScript", "CSS", "HTML",
             "Webpack", "Vite", "小程序", "浏览器", "Node")),
    ("人工智能", ("人工智能", "AI", "LLM", "大模型", "机器学习", "深度学习", "AIGC", "RAG")),
    ("Android", ("Android", "Kotlin", "Flutter", "Compose")),
    ("iOS", ("iOS", "Swift", "Objective-C")),
    ("开发工具", ("工具", "Git", "Linux", "Docker", "Kubernetes", "K8s", "CI", "效率")),
    ("后端", ("后端", "Java", "Go", "Python", "Spring", "MySQL", "Redis", "数据库",
             "微服务", "架构", "Kafka", "分布式", "消息队列", "Nginx", "Elasticsearch")),
]

# 推荐流发布窗口（社区共识：初始曝光池大小 + 早期互动率决定能否进下一级流量池）
_PUBLISH_WINDOW = {
    "首选": "工作日 08:30-09:30（通勤高峰，初始流量池曝光最大）",
    "次选": ["工作日 12:00-13:00（午休）", "工作日 21:00-22:30（晚间学习高峰）"],
    "避开": "周五晚、周末、法定节假日（互动率低，进不了下一级流量池）",
}

# 冷启动运营清单（发布后的动作，流水线管不到、但直接决定推荐放大）
_OPS_CHECKLIST = [
    "发布后 60 分钟内回复所有评论（早期互动率决定能否进入下一级流量池）",
    "发布当天不要删改文章；若 48h 数据差，可换用报告中的备选标题再观察",
    "分享到 1-2 个相关技术群或沸点即可，过度分发会被判引流",
    "保持每周 2-3 篇的更新节奏，账号活跃度影响初始池大小",
]


def _infer_category(tags: list[str]) -> str:
    """按 tags 推断掘金发布分类（推断不出返回空串，由作者手选）。"""
    for category, keywords in _JUEJIN_CATEGORY_RULES:
        for tag in tags:
            if any(kw.lower() in tag.lower() for kw in keywords):
                return category
    return ""


def extract_publish_info(blog_content: str) -> dict:
    """提取掘金发布表单所需信息：标题、备选标题、分类、标签、摘要、发布运营包。"""
    title_m = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", blog_content, re.MULTILINE)
    title = title_m.group(1) if title_m else ""
    tags_m = re.search(r"^tags:\s*\[(.*?)\]", blog_content, re.MULTILINE)
    tags = [t.strip() for t in tags_m.group(1).split(",")] if tags_m else []
    if not tags:  # YAML 多行列表形式（列表项必须有缩进，避免吞掉结尾的 ---）
        block_m = re.search(r"^tags:\n((?:[ \t]+-.*\n?)+)", blog_content, re.MULTILINE)
        tags = [m.strip() for m in re.findall(r"-\s*(.+)", block_m.group(1))] if block_m else []
    if not tags:  # 顿号/逗号分隔的裸字符串（非标准 YAML，模型偶尔输出）
        line_m = re.search(r"^tags:\s*(.+)$", blog_content, re.MULTILINE)
        if line_m and "[" not in line_m.group(1):
            tags = [t for t in re.split(r"[、,，]+", line_m.group(1).strip()) if t]

    # 备选标题：提示词要求 YAML 多行列表形式（标题自身可含逗号，不能用逗号切分）
    title_candidates: list[str] = []
    cand_block_m = re.search(
        r"^title_candidates:\n((?:[ \t]+-.*\n?)+)", blog_content, re.MULTILINE
    )
    if cand_block_m:
        title_candidates = [
            c.strip().strip("\"'") for c in re.findall(r"-\s*(.+)", cand_block_m.group(1))
        ]
    if not title_candidates and title:
        title_candidates = [title]

    summary_m = re.search(
        r"##\s*(?:TL;DR|太长不看|一句话结论|结论先行|速览|摘要)[^\n]*\n(.*?)(?=\n## |\n---\s*\n|\Z)",
        blog_content,
        re.DOTALL | re.IGNORECASE,
    )
    # 与 check_blog 口径一致：只取摘要小节的第一个段落
    summary = (
        re.sub(r"\s", "", summary_m.group(1).split("\n\n")[0])[:100] if summary_m else ""
    )

    return {
        "title": title[:40],
        "title_candidates": [c[:40] for c in title_candidates],
        "category": _infer_category(tags),
        "tags": tags[:6],
        "summary": summary,
        "publish_window": _PUBLISH_WINDOW,
        "ops_checklist": _OPS_CHECKLIST,
    }


def save_blog(blog_content: str, output_path: str) -> str:
    """保存博客到文件，返回文件绝对路径。

    自动创建输出目录（若不存在）。

    Args:
        blog_content: 博客 Markdown 内容。
        output_path: 目标文件路径（含 .md 扩展名）。

    Returns:
        保存后的文件绝对路径。
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(blog_content)

    return os.path.abspath(output_path)
