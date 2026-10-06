"""冒烟测试：确保所有模块可导入且核心函数签名正确。"""
import pytest


class TestImports:
    def test_cli_import(self):
        from src.cli import build_parser, load_dotenv, preflight_check
        parser = build_parser()
        assert parser is not None

    def test_downloader_import(self):
        from src.downloader import VideoDownloadError, download_video, get_video_title
        assert VideoDownloadError is not None

    def test_audio_import(self):
        from src.audio import extract_audio, get_video_duration, validate_video
        assert callable(extract_audio)

    def test_transcriber_import(self):
        from src.transcriber import Segment, transcribe
        seg = Segment(start=0.0, end=1.0, text="hello")
        assert seg.text == "hello"

    def test_synthesizer_import(self):
        from src.synthesizer import synthesize
        assert callable(synthesize)

    def test_postprocess_import(self):
        from src.postprocess import check_blog, save_blog
        assert callable(check_blog)

    def test_blog_rules_import(self):
        from src.blog_rules import BLOG_TEMPLATES, FORBIDDEN_PATTERNS, get_blog_template
        template = get_blog_template()
        assert "TL;DR" in template
        assert len(BLOG_TEMPLATES) >= 8
        assert any("Needless" in p for p in FORBIDDEN_PATTERNS)


class TestCheckBlog:
    def test_perfect_blog(self):
        from src.postprocess import check_blog
        content = """---
title: Python 排坑：3 个必踩的面试陷阱
---

## TL;DR
This is a test.

## Step 1

```python
print("hello")
```

## 进一步阅读
- 官方文档：Python 语言参考（自行搜索）
"""
        result = check_blog(content)
        assert result["score"] >= 9

    def test_no_tldr(self):
        from src.postprocess import check_blog
        content = """# Just a title
Some content.
"""
        result = check_blog(content)
        assert result["score"] < 10


class TestJuejinRecommend:
    """掘金推荐流优化相关检查（标题 CTR 要素 / 外链 / 发布信息提取）。"""

    @staticmethod
    def _blog(title: str, body: str = "正文内容。") -> str:
        return (
            f"---\ntitle: {title}\n"
            f"title_candidates:\n  - {title}\n---\n\n"
            f"## TL;DR\n摘要。\n\n{body}\n\n## 写在最后\n你遇到过吗？\n"
        )

    def test_title_ctr_pass(self):
        from src.postprocess import check_blog

        result = check_blog(self._blog("MySQL 索引失效的 7 个排查路径"))
        assert not any("CTR" in w for w in result["warnings"])

    def test_title_ctr_fail(self):
        from src.postprocess import check_blog

        result = check_blog(self._blog("MySQL 索引的使用方法总结"))
        assert any("CTR" in w for w in result["warnings"])

    def test_external_link_warns(self):
        from src.postprocess import check_blog

        result = check_blog(
            self._blog(
                "MySQL 索引失效的 7 个排查路径",
                body="参见 [文档](https://doc.example.com/x) 的说明。",
            )
        )
        assert any("站外链接" in w for w in result["warnings"])

    def test_publish_info_fields(self):
        from src.postprocess import extract_publish_info

        content = (
            "---\n"
            "title: React 事件失效的 3 个排查点\n"
            "title_candidates:\n"
            "  - React 事件失效的 3 个排查点\n"
            "  - 为什么 React 事件监听会失效？\n"
            "  - React 事件踩坑复盘：从失效到根治\n"
            "tags: [前端, React, 面试]\n"
            "---\n\n## TL;DR\n结论。\n"
        )
        info = extract_publish_info(content)
        assert info["category"] == "前端"
        assert len(info["title_candidates"]) == 3
        assert info["publish_window"]["首选"]
        assert info["ops_checklist"]

    def test_category_backend_fallback(self):
        from src.postprocess import extract_publish_info

        info = extract_publish_info(
            "---\ntitle: MySQL 为什么不走索引？\ntags: [MySQL, 后端, 面试]\n---\n\n## TL;DR\n结论。\n"
        )
        assert info["category"] == "后端"

    def test_candidates_fallback_to_title(self):
        from src.postprocess import extract_publish_info

        info = extract_publish_info(
            "---\ntitle: MySQL 为什么不走索引？\ntags: [MySQL]\n---\n\n## TL;DR\n结论。\n"
        )
        assert info["title_candidates"] == ["MySQL 为什么不走索引？"]

    def test_promote_ctr_title_swaps_in_passing_candidate(self):
        from src.postprocess import promote_ctr_title

        content = (
            "---\n"
            "title: MySQL 索引的使用方法总结\n"
            "title_candidates:\n"
            "  - MySQL 索引的使用方法总结\n"
            "  - 索引建好了 MySQL 却不走，回表到底贵在哪？\n"
            "---\n\n正文。\n"
        )
        promoted = promote_ctr_title(content)
        assert "title: 索引建好了 MySQL 却不走，回表到底贵在哪？" in promoted
        # 候选列表保持原样（作为后备）
        assert "MySQL 索引的使用方法总结" in promoted

    def test_promote_ctr_title_keeps_good_title(self):
        from src.postprocess import promote_ctr_title

        content = "---\ntitle: 索引失效的 7 种排查路径\n---\n\n正文。\n"
        assert promote_ctr_title(content) == content


class TestLoadDotenv:
    def test_missing_file(self):
        from src.cli import load_dotenv
        load_dotenv("/tmp/vertoscribe-nonexistent.env")


class TestFileNameClean:
    def test_special_chars(self):
        import re
        name = 'test/file:name*with?special"chars<>|'
        cleaned = re.sub(r'[/\\:*?"<>|]', '-', name)
        assert '/' not in cleaned
        assert '\\' not in cleaned
        assert ':' not in cleaned
