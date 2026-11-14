import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import sync_env

ROOT = Path(__file__).resolve().parents[1]


def run_sync(directory):
    return sync_env.main(["--directory", str(directory)])


def test_creates_from_example_without_printing_values(tmp_path, capsys):
    template = (ROOT / ".env.example").read_bytes()
    (tmp_path / ".env.example").write_bytes(template)

    assert run_sync(tmp_path) == 0

    target = tmp_path / ".env"
    assert target.read_bytes() == template
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    output = capsys.readouterr()
    assert ".env 생성 완료" in output.out
    assert "replace_with_" not in output.out
    assert "FMH_DATABASE_URL" not in output.out
    assert not output.err


def test_updates_template_layout_even_without_missing_keys(tmp_path, capsys):
    template = (
        "# =====\n# 한글 설정 양식\n# =====\nFIRST=first-default\n"
        "\n# 두 번째 설정\nSECOND=second-default\n# 양식 끝\n"
    )
    (tmp_path / ".env.example").write_text(template, encoding="utf-8")
    target = tmp_path / ".env"
    target.write_text(
        "# -----\n# Old layout\nSECOND='dummy-two' # keep inline\nFIRST=dummy-one\n",
        encoding="utf-8",
    )

    assert run_sync(tmp_path) == 0

    expected = template.replace("FIRST=first-default", "FIRST=dummy-one").replace(
        "SECOND=second-default", "SECOND='dummy-two' # keep inline"
    )
    assert target.read_text(encoding="utf-8") == expected
    metadata = target.stat()
    assert run_sync(tmp_path) == 0
    assert sync_env.file_version(target.stat()) == sync_env.file_version(metadata)
    output = capsys.readouterr()
    assert "dummy-one" not in output.out + output.err
    assert "dummy-two" not in output.out + output.err


def test_preserves_values_bom_and_crlf_while_adding_missing_keys(tmp_path, capsys):
    (tmp_path / ".env.example").write_text(
        "SECRET=public-placeholder\nEMPTY=default\nBARE=default\n"
        "LOCAL_IMAGE_PLATFORM=linux/amd64\n# New setting\nNEW_OPTION=default\n",
        encoding="utf-8",
    )
    original = (
        b'\xef\xbb\xbf# private comment\r\nexport SECRET="dummy$secret #=x"\r\n'
        b"EMPTY=\r\nBARE\r\nLOCAL_IMAGE_PLATFORM=linux/arm64\r\nCUSTOM=kept"
    )
    target = tmp_path / ".env"
    target.write_bytes(original)

    assert run_sync(tmp_path) == 0
    expected = (
        b'\xef\xbb\xbfexport SECRET="dummy$secret #=x"\r\nEMPTY=\r\nBARE\r\n'
        b"LOCAL_IMAGE_PLATFORM=linux/arm64\r\n# New setting\r\nNEW_OPTION=default\r\n\r\n"
        + sync_env.EXTRA_SECTION.replace("\n", "\r\n").encode("utf-8")
        + b"CUSTOM=kept\r\n"
    )
    assert target.read_bytes() == expected
    metadata = target.stat()

    assert run_sync(tmp_path) == 0
    assert target.read_bytes() == expected
    assert sync_env.file_version(target.stat()) == sync_env.file_version(metadata)
    output = capsys.readouterr()
    assert "1개 항목 추가" in output.out
    assert "이미 동기화되어 있습니다" in output.out
    assert "dummy" not in output.out + output.err
    assert "public-placeholder" not in output.out + output.err


@pytest.mark.parametrize("quote", ["'", '"'])
def test_multiline_values_do_not_hide_missing_keys(tmp_path, quote, capsys):
    (tmp_path / ".env.example").write_text(
        "SECRET=placeholder\nMISSING=outside\n", encoding="utf-8"
    )
    original = (
        f"SECRET={quote}first \\{quote} quote\nMISSING=inside-secret\nlast{quote} # keep\n"
    ).encode("utf-8")
    target = tmp_path / ".env"
    target.write_bytes(original)

    assert run_sync(tmp_path) == 0

    assert target.read_bytes() == original + b"MISSING=outside\n"
    output = capsys.readouterr()
    assert "inside-secret" not in output.out + output.err


@pytest.mark.parametrize("original", [
    b"SECRET='dummy-secret\n",
    b"not a key dummy-secret\n",
    b'SECRET="dummy-secret" trailing-value\n',
    b"SECRET=\xffdummy-secret\n",
    b"SECRET=dummy-secret\nSECRET=another-secret\n",
])
def test_invalid_existing_file_is_unchanged_and_errors_hide_values(tmp_path, original, capsys):
    (tmp_path / ".env.example").write_text("SECRET=placeholder\nNEW=default\n")
    target = tmp_path / ".env"
    target.write_bytes(original)
    metadata = target.stat()

    assert run_sync(tmp_path) == 1

    assert target.read_bytes() == original
    assert sync_env.file_version(target.stat()) == sync_env.file_version(metadata)
    assert not list(tmp_path.glob(".env-sync-*"))
    output = capsys.readouterr()
    assert output.err and not output.out
    assert "dummy-secret" not in output.err
    assert "another-secret" not in output.err


@pytest.mark.parametrize("template", [
    "SECRET=duplicate-one\nSECRET=duplicate-two\n",
    "# Empty template\n",
    "SECRET='unclosed-template\n",
    "SECRET\n",
])
def test_invalid_template_does_not_change_existing_file(tmp_path, template, capsys):
    (tmp_path / ".env.example").write_text(template)
    target = tmp_path / ".env"
    original = b"SECRET=dummy-secret\n"
    target.write_bytes(original)

    assert run_sync(tmp_path) == 1

    assert target.read_bytes() == original
    output = capsys.readouterr()
    assert not output.out
    assert "dummy-secret" not in output.err
    assert "duplicate-one" not in output.err
    assert "unclosed-template" not in output.err


def test_does_not_follow_target_symlink(tmp_path, capsys):
    (tmp_path / ".env.example").write_text("NEW=default\n")
    linked = tmp_path / "private-config"
    linked.write_bytes(b"SECRET=dummy-secret\n")
    target = tmp_path / ".env"
    target.symlink_to(linked)

    assert run_sync(tmp_path) == 1

    assert target.is_symlink()
    assert linked.read_bytes() == b"SECRET=dummy-secret\n"
    output = capsys.readouterr()
    assert "dummy-secret" not in output.out + output.err


def test_failed_replace_preserves_original_and_cleans_temporary(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("SECRET=placeholder\nNEW=default\n")
    target = tmp_path / ".env"
    original = b"SECRET=dummy-secret\n"
    target.write_bytes(original)

    def fail_replace(*args):
        raise OSError("dummy-secret")

    monkeypatch.setattr(sync_env.os, "replace", fail_replace)
    assert run_sync(tmp_path) == 1

    assert target.read_bytes() == original
    assert not list(tmp_path.glob(".env-sync-*"))
    output = capsys.readouterr()
    assert output.err and not output.out
    assert "dummy-secret" not in output.err


def test_creation_does_not_overwrite_concurrent_file(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env.example").write_text("SECRET=placeholder\n")
    target = tmp_path / ".env"
    original_link = os.link

    def create_before_link(source, destination):
        target.write_bytes(b"SECRET=concurrent-secret\n")
        original_link(source, destination)

    monkeypatch.setattr(sync_env.os, "link", create_before_link)
    assert run_sync(tmp_path) == 1

    assert target.read_bytes() == b"SECRET=concurrent-secret\n"
    assert not list(tmp_path.glob(".env-sync-*"))
    output = capsys.readouterr()
    assert "concurrent-secret" not in output.out + output.err


def test_formats_legacy_settings_like_repository_template(tmp_path, capsys):
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    (tmp_path / ".env.example").write_text(template, encoding="utf-8")
    expected = template.replace("IMAGE_TAG=latest", "IMAGE_TAG=test-deployed-version").replace(
        "LOCAL_IMAGE_PLATFORM=linux/amd64", "LOCAL_IMAGE_PLATFORM=linux/arm64"
    )
    assignments = [line for line in expected.splitlines() if line and not line.startswith("#")]
    target = tmp_path / ".env"
    target.write_text("# Old layout\n" + "\n".join(reversed(assignments)), encoding="utf-8")

    assert run_sync(tmp_path) == 0

    assert target.read_text(encoding="utf-8") == expected
    metadata = target.stat()
    assert run_sync(tmp_path) == 0
    assert sync_env.file_version(target.stat()) == sync_env.file_version(metadata)
    output = capsys.readouterr()
    assert "양식 갱신, 0개 항목 추가" in output.out
    assert "test-deployed-version" not in output.out + output.err
    assert "replace_with_" not in output.out + output.err


def test_preserves_extra_settings_and_notes_without_duplicating_sections(tmp_path, capsys):
    example = tmp_path / ".env.example"
    template = "# Current layout\nKNOWN=default\n# Template footer\n"
    example.write_text(template)
    target = tmp_path / ".env"
    target.write_text(
        "# Outdated layout\nKNOWN=stored\n\n# Custom note\nCUSTOM='dummy-secret'\n"
        "\n# Empty extra setting\nCUSTOM_EMPTY=\n# Local footer\n"
    )

    assert run_sync(tmp_path) == 0

    expected = (
        template.replace("KNOWN=default", "KNOWN=stored") + "\n" + sync_env.EXTRA_SECTION
        + "# Custom note\nCUSTOM='dummy-secret'\n\n# Empty extra setting\nCUSTOM_EMPTY=\n"
        "# Local footer\n"
    )
    assert target.read_text(encoding="utf-8") == expected
    assert run_sync(tmp_path) == 0
    assert target.read_text(encoding="utf-8") == expected

    example.write_text(template.replace("Template footer", "Updated footer"))
    assert run_sync(tmp_path) == 0
    assert target.read_text(encoding="utf-8") == expected.replace("Template footer", "Updated footer")
    output = capsys.readouterr()
    assert "dummy-secret" not in output.out + output.err


def test_removed_template_key_is_preserved_in_extra_settings(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("# Current settings\nKEEP=default\n# Old setting\nOLD=example\n")
    target = tmp_path / ".env"
    target.write_text("KEEP=custom\nOLD='dummy-secret'\n")
    assert run_sync(tmp_path) == 0

    example.write_text("# Current settings\nKEEP=default\n")
    assert run_sync(tmp_path) == 0

    expected = (
        "# Current settings\nKEEP=custom\n\n" + sync_env.EXTRA_SECTION
        + "# Old setting\nOLD='dummy-secret'\n"
    )
    assert target.read_text(encoding="utf-8") == expected
    assert run_sync(tmp_path) == 0
    assert target.read_text(encoding="utf-8") == expected


def test_layout_sync_preserves_newlines_inside_multiline_values(tmp_path):
    (tmp_path / ".env.example").write_text("# Updated layout\nFIRST=default\nSECRET=default\n")
    target = tmp_path / ".env"
    original_secret = b"SECRET='first line\nSECOND=inside-secret\r\nlast line' # inline\r\n"
    target.write_bytes(original_secret + b"FIRST=custom\r\n")

    assert run_sync(tmp_path) == 0

    assert target.read_bytes() == b"# Updated layout\r\nFIRST=custom\r\n" + original_secret


def test_template_without_final_newline_is_unchanged_on_second_run(tmp_path):
    (tmp_path / ".env.example").write_text("# Updated layout\nSECRET=default")
    target = tmp_path / ".env"
    target.write_bytes(b"SECRET='dummy-secret'\n")

    assert run_sync(tmp_path) == 0

    assert target.read_bytes() == b"# Updated layout\nSECRET='dummy-secret'"
    metadata = target.stat()
    assert run_sync(tmp_path) == 0
    assert sync_env.file_version(target.stat()) == sync_env.file_version(metadata)


def test_default_directory_is_script_project_not_working_directory(tmp_path):
    project = tmp_path / "project"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "sync_env.py"
    shutil.copy2(ROOT / "scripts/sync_env.py", script)
    (project / ".env.example").write_text("LOCAL_IMAGE_PLATFORM=linux/amd64\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / ".env").write_bytes(b"SECRET=unrelated-secret\n")

    completed = subprocess.run(
        ["uv", "run", "--no-env-file", "--no-project", "--no-sync", "--offline",
         "--python", sys.executable, str(script)],
        cwd=elsewhere, capture_output=True, text=True, check=True, timeout=30,
    )

    assert (project / ".env").read_text() == "LOCAL_IMAGE_PLATFORM=linux/amd64\n"
    assert (elsewhere / ".env").read_bytes() == b"SECRET=unrelated-secret\n"
    assert "unrelated-secret" not in completed.stdout + completed.stderr
