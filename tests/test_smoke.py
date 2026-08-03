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
        from src.blog_rules import get_blog_template, WRITING_RULES, FORBIDDEN_PATTERNS
        template = get_blog_template()
        assert "TL;DR" in template


class TestCheckBlog:
    def test_perfect_blog(self):
        from src.postprocess import check_blog
        content = """---
title: Test
---

## TL;DR
This is a test.

## Step 1

```python
print("hello")
```

## 进一步阅读
- [Link](https://example.com)
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
