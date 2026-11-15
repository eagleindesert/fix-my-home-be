"""API 문서의 타입·전송 계약을 런타임 상수로 변환한다.

실행: uv run python -m scripts.etc.generate_contract
업무 검증은 서비스 모듈에서 수행하며 이 도구는 정책을 추정하지 않는다.
"""

import pprint
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTION_PATTERN = re.compile(r"^### (.+)\n([\s\S]*?)(?=^#{2,3} |\Z)", re.M)
BLOCK_PATTERN = re.compile(r"^\*\*([^\n]+?)\*\*\s*$", re.M)


def rows(section):
    result = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip().replace("`", "") for cell in line.strip("|").split("|")]
        if len(cells) >= 2:
            result.append(cells)
    return result


def table_after(section, title):
    if title not in section:
        return []
    tail = section.split(title, 1)[1]
    table = []
    started = False
    for line in tail.splitlines():
        if line.startswith("|"):
            started = True
            table.append(line)
        elif started:
            break
    return rows("\n".join(table))


def trim_section(section):
    return re.sub(r"\n---\s*$", "", section).strip()


def endpoint_documentation(section):
    """Keep policy tables and prose; input/output tables get native OpenAPI fields."""
    blocks = list(BLOCK_PATTERN.finditer(section))
    description = [section[:blocks[0].start()].strip() if blocks else trim_section(section)]
    errors = {}
    response_description = ""
    for index, block in enumerate(blocks):
        title = block[1]
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(section)
        content = trim_section(section[block.end():end])
        if title == "예외 응답":
            for error in re.finditer(r"^- \*\*(\d{3}) [^\n]+?\*\*:\s*(.+)$", content, re.M):
                errors.setdefault(error[1], []).append(error[2])
        elif re.match(r"Response \d{3}", title):
            response_description = content
        elif (
            title not in ("Headers", "Response Headers", "Path Variables", "Query Parameters")
            and not title.startswith("Request Body")
        ):
            description.append(f"**{title}**\n\n{content}")
    return {
        "description": "\n\n".join(part for part in description if part),
        "path_parameters": [{"name": row[0], "type": row[1], "description": row[2]}
                            for row in table_after(section, "**Path Variables**")],
        "response_description": response_description,
        "response_headers": {row[0]: row[1] for row in table_after(section, "**Response Headers**")},
        "errors": errors,
    }


def generate(document):
    schemas, enums, endpoints = {}, {}, []
    schema_descriptions, enum_descriptions = {}, {}
    groups = list(re.finditer(r"^## \d+\. (.+) \((\w+)\)$", document, re.M))
    tags = [{"name": group[2], "description": group[1]} for group in groups]
    for match in SECTION_PATTERN.finditer(document):
        name, section = match.groups()
        endpoint = re.match(r"(GET|POST|PUT|PATCH|DELETE) `([^`]+)` — (.+)", name)
        if endpoint:
            method, path, summary = endpoint.groups()
            response = re.search(r"\*\*Response (\d+)", section)
            body = table_after(section, "**Request Body")
            query = table_after(section, "**Query Parameters**")
            response_table = table_after(section, "**Response " + response[1]) if response else []
            group = next(group for group in reversed(groups) if group.start() < match.start())
            endpoints.append({
                "method": method, "path": path, "summary": summary,
                "tag": group[2],
                **endpoint_documentation(section),
                "status": int(response[1]) if response else 200,
                "response": next((r[1] for r in response_table if r[0] == "data"), None),
                "authenticated": "**인증 요구사항**: ✅" in section,
                "idempotent": any(r[0] == "Idempotency-Key" for r in table_after(section, "**Headers**")),
                "multipart": "**Request Body (`multipart/form-data`)**" in section,
                "body": [
                    {"name": r[0], "type": r[1], "required": r[2] == "✅", "description": " · ".join(r[3:])}
                    for r in body
                ],
                "query": [
                    {"name": r[0], "type": r[1], "required": r[2] == "✅", "description": " · ".join(r[3:])}
                    for r in query
                ],
            })
        elif name.endswith("DTO") or name == "PageDTO<T>":
            fields = []
            # Only the first field table; following tables describe conditional policies.
            table = re.search(r"^\| 필드[^\n]*\n(?:\|[^\n]*\n?)+", section, re.M)
            if table:
                fields = rows(table[0])
                schema_descriptions[name] = trim_section(section[:table.start()] + section[table.end():])
            schemas[name] = [{"name": r[0], "type": r[1], "required": "✅" in r[2],
                              "description": r[2]} for r in fields]
        elif match.start() > document.index("## Enum 정의") and name != "ResourceStatus":
            enums[name] = [r[0] for r in rows(section)]
            enum_descriptions[name] = trim_section(section)
        elif name == "공통 에러 응답 구조":
            error_fields = [{"name": row[0], "type": row[1], "required": True,
                             "description": row[2]} for row in rows(section)]
            schemas["ErrorResponseDTO"] = error_fields
            schema_descriptions["ErrorResponseDTO"] = "오류는 data 래퍼 없이 루트 객체로 반환합니다."
    return {
        "ENUMS": enums,
        "ENUM_DESCRIPTIONS": enum_descriptions,
        "SCHEMAS": schemas,
        "SCHEMA_DESCRIPTIONS": schema_descriptions,
        "TAGS": tags,
        "ENDPOINTS": endpoints,
    }


def render_contract(document):
    contract = generate(document)
    header = '"""API명세서.md에서 생성됨. 원문 수정 후 uv run python -m scripts.etc.generate_contract 실행."""\n\n'
    return header + "\n\n".join(
        f"{name} = {pprint.pformat(value, sort_dicts=False, width=100)}"
        for name, value in contract.items()
    ) + "\n"


def main():
    document = (ROOT / "docs/API명세서.md").read_text(encoding="utf-8")
    contract = generate(document)
    target = ROOT / "app/contract_data.py"
    target.write_text(render_contract(document), encoding="utf-8")
    print(f"계약 생성: API {len(contract['ENDPOINTS'])}개, DTO {len(contract['SCHEMAS'])}개, Enum {len(contract['ENUMS'])}개")


if __name__ == "__main__":
    main()
