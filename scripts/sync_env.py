"""기존 값을 보존하면서 .env의 양식과 항목을 .env.example에 맞춘다.

실행: uv run scripts/sync_env.py
기존 .env는 실행 중 내부에서만 읽으며 값이나 파일 내용은 출력하지 않는다.
"""

import argparse
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = re.compile(r"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*(?:=(.*))?")
EXTRA_SECTION = (
    "# =============================================================================\n"
    "# .env.example에 없는 추가 설정\n"
    "# =============================================================================\n"
)


class EnvSyncError(Exception):
    """설정값을 포함하지 않는 오류 메시지."""


@dataclass(frozen=True)
class Entry:
    key: str
    leading: str = field(repr=False)
    assignment: str = field(repr=False)


@dataclass(frozen=True)
class EnvDocument:
    entries: list[Entry] = field(repr=False)
    trailing: str = field(repr=False)


def closing_quote(fragment: str, quote: str) -> int | None:
    escaped = False
    for index, character in enumerate(fragment):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return index
    return None


def parse_document(content: str, source: str, *, allow_unset: bool = False) -> EnvDocument:
    """값을 해석하거나 확장하지 않고 주석과 설정 원문을 분리한다."""
    lines = content.splitlines(keepends=True)
    entries = []
    index = block_start = 0
    while index < len(lines):
        line = lines[index].rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue

        assignment_start = index
        line_number = index + 1
        match = ASSIGNMENT.fullmatch(line)
        if match is None or (match[2] is None and not allow_unset):
            raise EnvSyncError(f"{source}의 {line_number}번째 줄 형식을 확인하세요.")
        value = (match[2] or "").lstrip(" \t")
        index += 1

        # 따옴표 안의 여러 줄은 KEY=value 모양이어도 별도 설정으로 취급하지 않는다.
        if value.startswith(("'", '"')):
            quote, fragment = value[0], value[1:]
            while True:
                end = closing_quote(fragment, quote)
                if end is not None:
                    remainder = fragment[end + 1:].strip()
                    if remainder and not remainder.startswith("#"):
                        raise EnvSyncError(f"{source}의 {line_number}번째 줄 형식을 확인하세요.")
                    break
                if index == len(lines):
                    raise EnvSyncError(f"{source}의 {line_number}번째 줄 따옴표를 확인하세요.")
                fragment = lines[index]
                index += 1

        entries.append(Entry(
            match[1],
            "".join(lines[block_start:assignment_start]),
            "".join(lines[assignment_start:index]),
        ))
        block_start = index
    return EnvDocument(entries, "".join(lines[block_start:]))


def layout_newlines(content: str, newline: str) -> str:
    return content.replace("\r\n", "\n").replace("\n", newline)


def render_document(
    template: EnvDocument, existing: EnvDocument, newline: str,
) -> tuple[str, int]:
    """양식의 주석·순서를 사용하고 기존 설정 줄과 여러 줄 값은 그대로 옮긴다."""
    current = {}
    for entry in existing.entries:
        if entry.key in current:
            raise EnvSyncError(".env에 중복된 키가 있습니다. 중복을 정리한 뒤 다시 실행하세요.")
        current[entry.key] = entry

    parts = []
    added = 0
    template_keys = {entry.key for entry in template.entries}
    for entry in template.entries:
        parts.append(layout_newlines(entry.leading, newline))
        if entry.key in current:
            assignment = current[entry.key].assignment
        else:
            assignment = layout_newlines(entry.assignment, newline)
            added += 1

        # 설정 줄 끝만 양식에 맞춘다. 따옴표 안의 줄바꿈·공백·이스케이프는 보존한다.
        ending = newline if entry.assignment.endswith(("\r", "\n")) else ""
        parts.append(assignment.rstrip("\r\n") + ending)

    parts.append(layout_newlines(template.trailing, newline))
    content = "".join(parts)
    extras = [entry for entry in existing.entries if entry.key not in template_keys]
    if extras:
        section = layout_newlines(EXTRA_SECTION, newline)
        content = content.rstrip("\r\n") + newline * 2 + section
        for index, entry in enumerate(extras):
            leading = layout_newlines(entry.leading, newline)
            # 양식에서 빠진 키가 기존 추가 설정보다 앞에 올 수도 있다.
            # 위치와 관계없이 이전 제목과 그 앞의 양식 맺음말을 제거한다.
            if section in leading:
                leading = leading.rsplit(section, 1)[1]
            if index == 0:
                leading = leading.lstrip("\r\n")
            content += leading + entry.assignment.rstrip("\r\n") + newline
        if existing.entries[-1].key not in template_keys:
            content += existing.trailing

    return content, added


def file_version(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def write_atomically(path: Path, content: bytes, previous: os.stat_result | None) -> None:
    """완성된 파일을 반영하며 새 파일과 임시 파일은 소유자만 읽고 쓸 수 있다."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".env-sync-", delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        if previous is None:
            # 검사 이후 다른 프로세스가 만든 .env를 덮어쓰지 않는다.
            os.link(temporary, path)
        else:
            if file_version(path.lstat()) != file_version(previous):
                raise EnvSyncError("처리 중 .env가 변경되었습니다. 다시 실행하세요.")
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sync_env(directory: Path) -> tuple[str, int]:
    example = directory / ".env.example"
    target = directory / ".env"
    if example.is_symlink():
        raise EnvSyncError(".env.example은 심볼릭 링크가 아닌 일반 파일이어야 합니다.")
    template = example.read_bytes()
    document = parse_document(template.decode("utf-8-sig"), ".env.example")
    keys = {entry.key for entry in document.entries}
    if not keys or len(keys) != len(document.entries):
        raise EnvSyncError(".env.example에는 중복되지 않는 KEY=value 항목이 필요합니다.")

    try:
        previous = target.lstat()
    except FileNotFoundError:
        write_atomically(target, template, None)
        return "created", len(keys)

    if not stat.S_ISREG(previous.st_mode):
        raise EnvSyncError(".env는 심볼릭 링크가 아닌 일반 파일이어야 합니다.")
    original = target.read_bytes()
    existing = parse_document(original.decode("utf-8-sig"), ".env", allow_unset=True)
    newline = "\r\n" if b"\r\n" in original else "\n"
    rendered, added = render_document(document, existing, newline)
    content = rendered.encode("utf-8")
    if original.startswith(b"\xef\xbb\xbf"):
        content = b"\xef\xbb\xbf" + content
    if content == original:
        return "unchanged", 0

    write_atomically(target, content, previous)
    return "updated", added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="기존 값을 보존하며 .env.example의 양식과 누락 항목을 반영합니다."
    )
    parser.add_argument(
        "--directory", type=Path, default=ROOT, metavar="PATH",
        help=".env.example과 .env가 있는 디렉터리 (기본값: 저장소 루트)",
    )
    args = parser.parse_args(argv)
    try:
        result, count = sync_env(args.directory)
    except EnvSyncError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        # 예외 원문에는 파일 내용이 들어갈 수 있으므로 출력하지 않는다.
        print("동기화에 실패했습니다. 파일 경로·권한·UTF-8 인코딩을 확인하세요.", file=sys.stderr)
        return 1

    if result == "created":
        print(f".env 생성 완료: {count}개 항목. 예시 값을 실제 환경에 맞게 설정하세요.")
    elif result == "updated":
        print(f".env 동기화 완료: 양식 갱신, {count}개 항목 추가. 기존 값은 유지했습니다.")
    else:
        print("양식과 설정 항목이 이미 동기화되어 있습니다. .env를 변경하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
