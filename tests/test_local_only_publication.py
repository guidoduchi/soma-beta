"""Exercise publication guards with synthetic files in isolated repositories."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("local_only_guard", Path(__file__).resolve().parents[1] / "tools/check_local_only.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True).stdout
    git("init", "--quiet")
    git("config", "user.name", "Synthetic Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "public.txt").write_text("public synthetic fixture", encoding="utf-8")
    git("add", "public.txt")
    git("commit", "--quiet", "-m", "synthetic baseline")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    return tmp_path, git


def test_ignore_blocks_normal_staging_and_guard_blocks_forced_staging(repo):
    root, git = repo
    (root / ".gitignore").write_text("/tmp/\n", encoding="utf-8")
    private = root / "tmp" / "example.eml"
    private.parent.mkdir()
    private.write_text("synthetic placeholder", encoding="utf-8")
    git("add", "--all")
    guard.check()
    git("add", "--force", "tmp/example.eml")
    with pytest.raises(ValueError, match="staged or tracked") as failure:
        guard.check()
    assert "example.eml" not in str(failure.value) and "placeholder" not in str(failure.value)


def test_removed_private_file_still_blocks_history_publication(repo):
    root, git = repo
    private = root / "tmp" / "example.eml"
    private.parent.mkdir()
    private.write_text("synthetic placeholder", encoding="utf-8")
    git("add", "tmp/example.eml")
    git("commit", "--quiet", "-m", "synthetic private history")
    git("rm", "tmp/example.eml")
    git("commit", "--quiet", "-m", "synthetic removal")
    with pytest.raises(ValueError, match="publication history"):
        guard.check()


def test_push_guard_checks_each_pushed_branch_history(repo, monkeypatch):
    import io
    root, git = repo
    public = git("rev-parse", "HEAD").decode().strip()
    private = root / "tmp" / "example.eml"
    private.parent.mkdir()
    private.write_text("synthetic placeholder", encoding="utf-8")
    git("add", "tmp/example.eml")
    git("commit", "--quiet", "-m", "synthetic private branch")
    private_ref = git("rev-parse", "HEAD").decode().strip()
    git("checkout", "--quiet", "--detach", public)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"refs/heads/private {private_ref} refs/heads/private {'0'*40}\n"))
    with pytest.raises(ValueError, match="publication history"):
        guard.check(pre_push=True)


def test_clean_push_and_deletion_are_permitted(repo, monkeypatch):
    import io
    _, git = repo
    ref = git("rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr("sys.stdin", io.StringIO(f"refs/heads/clean {ref} refs/heads/clean {'0'*40}\n"))
    guard.check(pre_push=True)
    monkeypatch.setattr("sys.stdin", io.StringIO(f"(delete) {'0'*40} refs/heads/old {ref}\n"))
    guard.check(pre_push=True)


def test_malformed_push_metadata_fails_closed(repo, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("malformed input\n"))
    with pytest.raises(ValueError, match="metadata"):
        guard.check(pre_push=True)


def test_archive_exclusion_covers_even_a_forced_private_commit(repo):
    import io
    import zipfile
    root, git = repo
    source_root = Path(__file__).resolve().parents[1]
    (root / ".gitattributes").write_bytes((source_root / ".gitattributes").read_bytes())
    private = root / "tmp" / "nested" / "example.eml"
    private.parent.mkdir(parents=True)
    private.write_text("synthetic placeholder", encoding="utf-8")
    git("add", ".gitattributes", "tmp/nested/example.eml")
    git("commit", "--quiet", "-m", "synthetic archive fixture")
    with zipfile.ZipFile(io.BytesIO(git("archive", "--format=zip", "HEAD"))) as archive:
        assert not any(path == "tmp" or path.startswith("tmp/") for path in archive.namelist())
        assert "public.txt" in archive.namelist()
