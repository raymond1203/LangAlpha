from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="class")]


class TestFileOperations:
    """PTCSandbox file I/O: upload, download, read, write, edit, glob, grep, list."""

    async def test_upload_and_download(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        ok = await shared_sandbox.aupload_file_bytes(f"{wd}/results/test.txt", b"file content")
        assert ok is True
        content = await shared_sandbox.adownload_file_bytes(f"{wd}/results/test.txt")
        assert content == b"file content"

    async def test_read_text(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/readme.txt", b"Hello, World!")
        text = await shared_sandbox.aread_file_text(f"{wd}/data/readme.txt")
        assert text == "Hello, World!"

    async def test_write_text(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        ok = await shared_sandbox.awrite_file_text(f"{wd}/data/written.txt", "written via API")
        assert ok is True
        text = await shared_sandbox.aread_file_text(f"{wd}/data/written.txt")
        assert text == "written via API"

    async def test_read_file_range(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        lines = "\n".join(f"line {i}" for i in range(1, 21))
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/multiline.txt", lines.encode())
        content = await shared_sandbox.aread_file_range(f"{wd}/data/multiline.txt", offset=4, limit=6)
        assert content is not None
        result_lines = content.strip().split("\n")
        assert "line 5" in result_lines[0]

    async def test_edit_file(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        await shared_sandbox.awrite_file_text(f"{wd}/data/editable.txt", "Hello, old world!")
        result = await shared_sandbox.aedit_file_text(
            f"{wd}/data/editable.txt", "old world", "new world"
        )
        assert result["success"] is True
        text = await shared_sandbox.aread_file_text(f"{wd}/data/editable.txt")
        assert text == "Hello, new world!"

    async def test_edit_file_not_found(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        result = await shared_sandbox.aedit_file_text(
            f"{wd}/data/nonexistent.txt", "old", "new"
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    async def test_edit_file_old_string_not_found(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        await shared_sandbox.awrite_file_text(f"{wd}/data/edit_miss.txt", "Hello world")
        result = await shared_sandbox.aedit_file_text(
            f"{wd}/data/edit_miss.txt", "nonexistent string", "new"
        )
        assert result["success"] is False

    async def test_create_directory(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        ok = await shared_sandbox.acreate_directory(f"{wd}/new_dir/sub")
        assert ok is True
        result = await shared_sandbox.execute_bash_command(
            f"test -d {wd}/new_dir/sub && echo OK", working_dir=wd
        )
        assert "OK" in result["stdout"]

    async def test_list_directory(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/list_a.txt", b"a")
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/list_b.txt", b"b")

        entries = await shared_sandbox.als_directory(f"{wd}/data")
        names = {e["name"] for e in entries}
        assert "list_a.txt" in names
        assert "list_b.txt" in names

    async def test_glob_files(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/file1.py", b"# py1")
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/file2.py", b"# py2")
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/file3.txt", b"text")

        matches = await shared_sandbox.aglob_files("*.py", path=f"{wd}/data")
        assert len(matches) >= 2
        py_matches = [m for m in matches if m.endswith(".py")]
        assert len(py_matches) >= 2

    async def test_grep_content(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        await shared_sandbox.aupload_file_bytes(
            f"{wd}/data/searchable.txt", b"apple\nbanana\ncherry\napricot\n"
        )
        matches = await shared_sandbox.agrep_content(
            "ap", path=f"{wd}/data", output_mode="content"
        )
        assert len(matches) > 0
        match_text = "\n".join(matches)
        assert "apple" in match_text or "apricot" in match_text

    async def test_grep_files_with_matches(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/grep1.txt", b"hello world\n")
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/grep2.txt", b"goodbye world\n")
        await shared_sandbox.aupload_file_bytes(f"{wd}/data/grep3.txt", b"no match here\n")

        matches = await shared_sandbox.agrep_content(
            "world", path=f"{wd}/data", output_mode="files_with_matches"
        )
        assert len(matches) >= 2

    async def test_download_nonexistent(self, shared_sandbox):
        wd = shared_sandbox._work_dir
        content = await shared_sandbox.adownload_file_bytes(f"{wd}/data/nope.txt")
        assert content is None

    async def test_upload_denied_path(self, shared_sandbox):
        """Path in denied_directories should be rejected."""
        wd = shared_sandbox._work_dir
        # Add a denied directory to test denial
        shared_sandbox.config.filesystem.denied_directories = [f"{wd}/_internal"]
        ok = await shared_sandbox.aupload_file_bytes(f"{wd}/_internal/secret.txt", b"hack")
        assert ok is False
        # Restore
        shared_sandbox.config.filesystem.denied_directories = []
