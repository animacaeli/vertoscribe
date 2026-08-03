"""博客后处理：规范检查与文件保存。"""
from __future__ import annotations

import os
import re

from src.blog_rules import FORBIDDEN_PATTERNS


def check_blog(blog_content: str) -> dict:
    """检查博客内容是否符合 technical-blog-writing 规范。

    返回 {"score": int, "warnings": list[str]}。
    score: 满分 10，每违反一条规则扣 1 分，最低为 0。

    检查项：
        1. 是否有 TL;DR 段落（无则扣 1 分）
        2. 是否有进一步阅读段落（无则扣 1 分）
        3. 是否包含 FORBIDDEN_PATTERNS 中的禁用词（每发现一类扣 1 分）
        4. 代码块是否标注语言类型（检测 ``` 后是否紧跟语言名）
        5. 是否有 YAML frontmatter（文件以 --- 开头）
    """
    warnings: list[str] = []
    score = 10

    # 1. 检查 TL;DR 段落
    if not re.search(r"##\s*TL;DR", blog_content, re.IGNORECASE):
        warnings.append("缺少 TL;DR 摘要段落（## TL;DR）")
        score -= 1

    # 2. 检查进一步阅读/参考段落
    if not re.search(
        r"##\s*(?:进一步阅读|Further Reading|参考|References|相关资源)",
        blog_content,
        re.IGNORECASE,
    ):
        warnings.append("缺少进一步阅读/参考段落")
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
    #    匹配 ``` 后紧跟换行（即未标注语言）的情况
    unlabeled_blocks = re.findall(r"```\s*\n", blog_content)
    if unlabeled_blocks:
        count = len(unlabeled_blocks)
        warnings.append(f"有 {count} 个代码块未标注语言类型（``` 后未跟语言名）")
        score -= 1

    # 5. 检查 YAML frontmatter（文件以 --- 开头）
    if not re.match(r"^---\s*\n", blog_content):
        warnings.append("缺少 YAML frontmatter（文件应以 --- 开头）")
        score -= 1

    return {"score": max(0, score), "warnings": warnings}


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
