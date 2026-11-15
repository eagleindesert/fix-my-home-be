# AI 평가 실행

평가 도구는 `scripts/etc/evaluate_ai.py`입니다. 이 저장소에는 출처와 사용 권리가 확인된 80개 평가 사례가 제공되지 않았으므로 실제 모델 평가 결과를 포함하지 않습니다. 테스트의 가짜 모델은 상태·실패 처리 검증용이며 AI 품질 점수가 아닙니다.

## 사전 고정

평가군은 `diagnosis`, `self_help`, `emergency_failure`, `case_matching`, `schedule_price`, `photo_comparison`, `handover`, `questions`입니다. 각 군에 최소 10개 기준 사례를 준비하고 각 사례를 3회 실행합니다.

manifest에는 `version`, `model`, `rubricVersion`, `sampleSeed`, `cases`, `injections`를 지정합니다. 각 case에는 다음 정보를 둡니다.

- `id`, `group`: 군별 고유 사례와 평가군.
- `provenance`: `kind`(MOCK 또는 REPRODUCED), `source`, `usageBasis`, `identifiersRemoved`, `reviewedBy`.
- `input`: 생성기에 제공할 작업 유형·사진/증상·기존 답변·검증 자료.
- `images`: 선택적인 `{photoId, path}` 배열. 파일은 manifest 디렉토리 내부에 둡니다.
- `expected`, `requiredOutput`, `allowedAnswers`, `rubric`: 출력 생성 전에 고정한 정답과 판정 기준.
- `metrics`: 지표별 `{units, exclusionReason?}`. units는 사전 고정 분모이며 0이면 제외·산출 불가 사유가 필요합니다.

지표 이름과 합격선은 도구의 `THRESHOLDS`에 있습니다. 전체 manifest에 모든 지표를 포함해야 합니다. 오류 주입에는 GUIDE와 PHOTO 사례를 각각 포함하며 `id`, `kind`, `caseId`, `output`, `expectedCritical`을 지정합니다. 주입 출력은 생성 품질 분모에 넣지 않습니다.

```bash
uv run python -m scripts.etc.evaluate_ai prepare dataset/manifest.json evaluation-results/v1
```

이 명령은 사진 해시, 데이터셋, 루브릭, 모델, 프롬프트, 목표값, 반복 횟수와 표본 선정 seed를 고정합니다. 고정 결과를 수정하면 실행을 거부합니다. 실제 접수자료의 저장소·API·사진 URL을 평가로 가져오는 기능은 없습니다.

## 실행과 사람 검토

```bash
export FMH_OPENAI_API_KEY='configured-outside-the-repository'
# 별도 서버 사용 시 Responses API를 지원하는 기본 URL을 지정합니다.
# export FMH_OPENAI_BASE_URL='https://ai.example.com/v1'
uv run python -m scripts.etc.evaluate_ai run evaluation-results/v1
uv run python -m scripts.etc.evaluate_ai report evaluation-results/v1
```

`run`은 유료 모델 요청을 발생시킵니다. 생성·평가에 manifest의 같은 모델을 사용하며 별도 Responses 호출과 별도 프롬프트로 문맥을 분리합니다. 모델 제공자가 세부 버전을 공개하지 않으면 모델 이름 이상의 재현성을 보장할 수 없습니다. 평가기가 서비스를 생성한 같은 모델이므로 독립된 외부 검증이라고 해석하지 않습니다.

원출력·오류·평가 결과는 실행별 JSON에 남습니다. 이미 기록된 회차를 덮어쓰지 않습니다. 프롬프트·모델·자료를 변경하면 새 디렉토리와 새 버전을 사용합니다. 서비스 DB 작업 큐의 재시도·60초 전체 제한·권한·상태 전이는 별도의 통합 테스트로 검증합니다. 평가 도구의 생성 호출만으로 전체 API 흐름 합격을 판정하지 않습니다.

`human-sample.json`은 군별 20% 올림·최소 5건, 각 회차와 관측된 통과·실패·보류 범주를 포함합니다. 최소 30실행이면 군별 6건입니다. 치명 실패 의심과 이견 사례는 이 표본에 추가해 검토합니다. `human-reviews.json`에 다음 정보를 기록합니다.

```json
[
  {
    "caseId": "prepared-case-id",
    "repetition": 1,
    "reviewer": "검토자 식별값",
    "reason": "원본과 대조한 판단 근거",
    "unresolved": false,
    "finalEvaluation": {
      "critical": false,
      "reason": "판정 근거",
      "metrics": {
        "field_accuracy": {"achieved": 1, "held": false, "reason": "정답 집합 일치"}
      }
    }
  }
]
```

`finalEvaluation.metrics`에는 해당 사례의 모든 지표를 기입합니다. 원래 모델 판정은 runs 파일에 유지합니다. 무출력은 실패이며 최소 지표에서는 0, 5점 척도에서는 1점으로 집계합니다. 주장·질문이 없는 무출력의 오류 비율은 0%로 처리하지 않고 산출 불가를 기록합니다. 사람 검토·오류 주입·실행 수가 부족하면 `INCOMPLETE_OR_FAILED`로 남깁니다. 최종 AC 검수에는 별도의 사용자·기사 화면 증거도 필요합니다.
