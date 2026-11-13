"""API 문서의 타입·전송 계약을 런타임 상수로 변환한다.

실행: uv run python -m scripts.generate_contract
업무 검증은 서비스 모듈에서 수행하며 이 도구는 정책을 추정하지 않는다.
"""

import pprint
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def main():
    document = (ROOT / "docs/API명세서.md").read_text()
    schemas, enums, endpoints = {}, {}, []
    for match in re.finditer(r"^### (.+)\n([\s\S]*?)(?=^#{2,3} |\Z)", document, re.M):
        name, section = match.groups()
        endpoint = re.match(r"(GET|POST|PUT|PATCH|DELETE) `([^`]+)` — (.+)", name)
        if endpoint:
            method, path, summary = endpoint.groups()
            response = re.search(r"\*\*Response (\d+)", section)
            body = table_after(section, "**Request Body")
            query = table_after(section, "**Query Parameters**")
            response_table = table_after(section, "**Response " + response[1]) if response else []
            endpoints.append({
                "method": method, "path": path, "summary": summary,
                "status": int(response[1]) if response else 200,
                "response": next((r[1] for r in response_table if r[0] == "data"), None),
                "authenticated": "**인증 요구사항**: ✅" in section,
                "idempotent": any(r[0] == "Idempotency-Key" for r in table_after(section, "**Headers**")),
                "multipart": "**Request Body (`multipart/form-data`)**" in section,
                "body": [{"name": r[0], "type": r[1], "required": r[2] == "✅", "description": " · ".join(r[3:])} for r in body],
                "query": [{"name": r[0], "type": r[1], "required": r[2] == "✅", "description": " · ".join(r[3:])} for r in query],
            })
        elif name.endswith("DTO") or name == "PageDTO<T>":
            fields = []
            # Only the first field table; following tables describe conditional policies.
            table = re.search(r"^\| 필드[^\n]*\n(?:\|[^\n]*\n?)+", section, re.M)
            if table:
                fields = rows(table[0])
            schemas[name] = [{"name": r[0], "type": r[1], "required": "✅" in r[2],
                              "description": r[2]} for r in fields]
        elif match.start() > document.index("## Enum 정의") and name != "ResourceStatus":
            enums[name] = [r[0] for r in rows(section)]
    target = ROOT / "app/contract_data.py"
    target.write_text('"""API명세서.md에서 생성됨. 수정 후 generate_contract를 실행하세요."""\n\n' +
                      "ENUMS = " + pprint.pformat(enums, sort_dicts=False, width=100) + "\n\n" +
                      "SCHEMAS = " + pprint.pformat(schemas, sort_dicts=False, width=100) + "\n\n" +
                      "ENDPOINTS = " + pprint.pformat(endpoints, sort_dicts=False, width=100) + "\n")
    print(f"계약 생성: API {len(endpoints)}개, DTO {len(schemas)}개, Enum {len(enums)}개")


if __name__ == "__main__":
    main()
