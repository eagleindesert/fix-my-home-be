#!/usr/bin/env bash
# 기획서의 선택 문답·사례 추천·경과 분석. 모든 상태 변경은 HTTP로 수행한다.

submit_item_ai() {
    local kind=$1
    refresh_request
    request user POST "/requests/$REQUEST_ID/ai-jobs" 202 "$(json --arg kind "$kind" --argjson item "$ITEM" \
        '{type:$kind,sourceRevision:$item.sourceRevision,workItemId:$item.workItemId}')"
    AI_JOB_ID=$(value '.data.jobId')
    poll_job "/ai-jobs/$AI_JOB_ID" "$AI_STATUS"
    if [[ $AI_STATUS == FAILED ]]; then
        assert_json '.data.result == null and .data.error.code == $code' \
            '명시된 AI 실패 원인' --arg code "$(config_value '.ai.expectedErrorCode')"
    fi
}

check_ai_dialogue() {
    local AI_JOB_ID question_id count
    submit_item_ai QUESTION
    [[ $AI_STATUS == SUCCEEDED ]] || return 0
    question_id=$(value '.data.result.question.questionId')
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    count=$(jq '.data.items | length' "$RESPONSE_FILE")
    refresh_request
    request user PUT "/requests/$REQUEST_ID/ai-dialogue" 200 "$(json --argjson root "$ROOT" --arg question "$question_id" \
        '{expectedRevision:$root.dialogue.revision,action:"ANSWER",questionId:$question,
          answer:"이틀 전 발견했고 물을 사용할 때 반복됩니다. 마른 천으로 닦았지만 다시 젖었습니다."}')"
    assert_json '.data.completedRounds == 1 and .data.finished == false and
        (.data.questions[0].answer | contains("다시 젖었습니다"))' '발행된 AI 질문에 사용자 답변 저장'
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    assert_json '(.data.items | length) == $count' '답변만으로 유료 AI 자동 실행 안 함' --argjson count "$count"
    request user GET "/ai-jobs/$AI_JOB_ID" 200
    assert_json '.data.stale == true and .data.result == null' '답변 후 이전 분석 근거 만료'
    # 다음 check_ai가 사용자의 명시적인 새 DIAGNOSIS 요청을 수행한다.
}

check_case_matching() {
    local AI_JOB_ID
    submit_item_ai CASE_MATCHING
    [[ $AI_STATUS == SUCCEEDED ]] || return 0
    request user GET "/work-items/$ITEM_ID/case-recommendations" 200
    assert_json '.data.evaluationStatus == "COMPLETED" and .data.stale == false and
        any(.data.recommendations[];
            .candidate.technician.technicianId == $technician and .candidate.timeFit == "MATCHED" and
            any(.cases[]; .case.caseId == $case and .score >= 3 and (.evidence | length) > 0))' \
        '실제 등록 사례의 근거와 조건 충족 기사 추천' --arg technician "$TECH_ID" --arg case "$CASE_ID"
}

wall_photo_path() {
    local path
    path=$(config_value ".wallPhotos.$1")
    if [[ $path != /* ]]; then path="$(dirname -- "$CONFIG")/$path"; fi
    printf '%s' "$path"
}

compare_progression_pair() {
    local first=$1 second=$2 expected=$3 group_id source
    refresh_request
    request user PUT "/requests/$REQUEST_ID/photo-groups" 200 "$(json --argjson root "$ROOT" \
        --arg first "$first" --arg second "$second" --argjson photos "$PROGRESS_PHOTOS" \
        '{sourceRevision:$root.sourceRevision,
          groups:[{label:"WALL_STAIN 벽지 물자국",photoIds:$photos,selectedPhotoIds:[$first,$second]}]}')"
    request user GET "/requests/$REQUEST_ID/timeline" 200
    assert_json '(.data.retakeGuide | length) > 0 and (.data.groups[0].comparisonPhotoIds | length) == 2' \
        '같은 부위 비교쌍과 재촬영 안내'
    group_id=$(value '.data.groups[0].groupId')
    source=$(value '.data.groups[0].sourceRevision')
    request user POST "/requests/$REQUEST_ID/ai-jobs" 202 "$(json --arg group "$group_id" --arg source "$source" \
        '{type:"PHOTO_COMPARISON",sourceRevision:$source,photoGroupId:$group}')"
    AI_JOB_ID=$(value '.data.jobId')
    poll_job "/ai-jobs/$AI_JOB_ID" "$AI_STATUS"
    if [[ $AI_STATUS == FAILED ]]; then
        assert_json '.data.error.code == $code' '사진 비교의 명시된 실패' --arg code "$(config_value '.ai.expectedErrorCode')"
        return
    fi
    assert_json '.data.result.comparison.status == $expected and .data.result.comparison.causeUnknown == true and
        .data.result.comparison.photoIds == [$first,$second]' '변화·무변화·비교 불가 구분과 원본 근거' \
        --arg expected "$expected" --arg first "$first" --arg second "$second"
    if [[ $expected == INCOMPARABLE ]]; then
        assert_json '.data.result.comparison.chronologyKnown == false and
            (.data.result.comparison.regions | length) == 0 and
            (.data.result.comparison.retakeGuide | length) > 0' '날짜 미확인 시 변화 방향 판단 유보'
    else
        assert_json '.data.result.comparison.chronologyKnown == true' '확인한 날짜 순서로 비교'
    fi
}

save_progression_report() {
    local expected_revision=$1
    refresh_request
    request user PUT "/work-items/$ITEM_ID/report" 200 "$(json --argjson revision "$expected_revision" \
        --argjson item "$ITEM" --argjson report "$PROGRESS_REPORT" \
        '{expectedRevision:$revision,sourceRevision:$item.sourceRevision,report:$report}')"
    request user PUT "/work-items/$ITEM_ID/report/confirmation" 200 "$(jq -c \
        '{expectedRevision:.data.revision,sourceRevision:.data.sourceRevision,confirmed:true}' "$RESPONSE_FILE")"
    assert_json '.data.reviewStatus == "CONFIRMED" and
        (.data.current.content.facts | any((.photoIds | length) > 0 and (.recordIds | length) > 0))' \
        '사용자가 확인한 경과 보고서의 사진·기록 근거'
}

publish_progression_pdf() {
    local delivery_id revision
    refresh_request
    request user POST "/work-items/$ITEM_ID/deliveries" 202 "$(json --argjson item "$ITEM" \
        --argjson photos "$PROGRESS_PHOTOS" --arg record "$PROGRESS_RECORD_ID" \
        '{sourceRevision:$item.sourceRevision,scope:{purpose:"EXTERNAL_PDF",photoIds:$photos,
          recordIds:[$record],questionIds:[],includeSummary:false,includeReport:true,includeQuoteContext:false},
          redactions:[] }')"
    delivery_id=$(value '.data.deliveryId')
    poll_job "/deliveries/$delivery_id" READY
    request user PUT "/deliveries/$delivery_id/confirmation" 200 "$(jq -c \
        '{expectedRevision:.data.revision,sourceRevision:.data.sourceRevision,confirmed:true}' "$RESPONSE_FILE")"
    revision=$(value '.data.revision')
    assert_json '(.data.content.photos | length) == 4 and (.data.content.records | length) == 1' \
        '경과 사진과 조치 기록을 포함한 외부 전달본'
    request user POST "/deliveries/$delivery_id/pdf-jobs" 202 "$(json --arg revision "$revision" '{deliveryRevision:$revision}')"
    PROGRESS_PDF_ID=$(value '.data.jobId')
    poll_job "/pdf-jobs/$PROGRESS_PDF_ID" READY
    request user GET "/pdf-jobs/$PROGRESS_PDF_ID/content" 200
    [[ $(head -c 5 "$RESPONSE_FILE") == '%PDF-' ]] || die '경과 보고서 PDF 형식 오류'
}

check_photo_progression() {
    # 호출자의 주 요청·예약 변수를 보존하되 HTTP 호출·검증 횟수는 함께 누적한다.
    local REQUEST_ID ITEM_ID ROOT ITEM PHOTO_ID MEDIA_ID AI_JOB_ID
    local PROGRESS_PHOTOS PROGRESS_RECORD_ID PROGRESS_REPORT PROGRESS_PDF_ID
    local before after unchanged incomparable dates metadata count old_job old_pdf old_source report_revision
    before=$(wall_photo_path before)
    after=$(wall_photo_path after)
    unchanged=$(wall_photo_path unchanged)
    incomparable=$(wall_photo_path incomparable)
    dates=$(json '{before:(now-172800|strftime("%Y-%m-%d")),after:(now-86400|strftime("%Y-%m-%d"))}')
    metadata=$(json --argjson region "$REGION" --argjson dates "$dates" \
        '{symptom:"WALL_STAIN 벽지 물자국의 날짜별 경과 확인",region:$region,
          photos:[{capturedOn:$dates.before,dateConfirmed:true,description:"최초 물자국"},
                  {capturedOn:$dates.after,dateConfirmed:true,description:"다음 날 물자국"},
                  {capturedOn:$dates.after,dateConfirmed:true,description:"변화 없는 비교 자료"},
                  {capturedOn:null,dateConfirmed:false,description:"촬영일 미확인 자료"}]}')
    request user POST /requests 201 '' \
        --form "files=@\"$before\";filename=before.png;type=image/png" \
        --form "files=@\"$after\";filename=after.png;type=image/png" \
        --form "files=@\"$unchanged\";filename=unchanged.png;type=image/png" \
        --form "files=@\"$incomparable\";filename=incomparable.png;type=image/png" \
        --form-string "metadata=$metadata"
    ROOT=$(data)
    REQUEST_ID=$(value '.data.requestId')
    ITEM_ID=$(value '.data.workItems[0].workItemId')
    # 응답은 날짜별로 정렬되므로 설명으로 입력 사진을 안정적으로 식별한다.
    PROGRESS_PHOTOS=$(jq -c '[.data.photos.confirmedDatePhotos[],.data.photos.unknownDatePhotos[]]
        | sort_by(.description) | map(.photoId)' "$RESPONSE_FILE")
    local all_photos
    all_photos=$(jq -c '[.data.photos.confirmedDatePhotos[],.data.photos.unknownDatePhotos[]]' "$RESPONSE_FILE")
    before=$(jq -r '.[] | select(.description == "최초 물자국") | .photoId' <<< "$all_photos")
    after=$(jq -r '.[] | select(.description == "다음 날 물자국") | .photoId' <<< "$all_photos")
    unchanged=$(jq -r '.[] | select(.description == "변화 없는 비교 자료") | .photoId' <<< "$all_photos")
    incomparable=$(jq -r '.[] | select(.description == "촬영일 미확인 자료") | .photoId' <<< "$all_photos")
    request user POST "/requests/$REQUEST_ID/records" 201 "$(json --arg item "$ITEM_ID" --arg photo "$after" \
        --argjson dates "$dates" '{record:{description:"비 온 다음 날 물자국을 관찰하고 마른 천으로 닦았으나 다시 보임",
        occurredOn:$dates.after,photoIds:[$photo],workItemIds:[$item]}}')"
    PROGRESS_RECORD_ID=$(value '.data.recordId')
    compare_progression_pair "$before" "$after" CHANGED
    compare_progression_pair "$before" "$unchanged" UNCHANGED
    compare_progression_pair "$before" "$incomparable" INCOMPARABLE

    submit_item_ai REPORT_DRAFT
    old_job=$AI_JOB_ID
    if [[ $AI_STATUS == SUCCEEDED ]]; then
        PROGRESS_REPORT=$(jq -c '.data.result.reportDraft' "$RESPONSE_FILE")
        assert_json '(.data.result.reportDraft.photoIds | length) == 4 and
            (.data.result.reportDraft.facts | any((.recordIds | length) > 0))' 'AI 초안의 원본 사진·조치 기록 근거'
    else
        PROGRESS_REPORT=$(json --argjson photos "$PROGRESS_PHOTOS" --arg record "$PROGRESS_RECORD_ID" \
            '{markdown:"# 직접 정리한 벽지 물자국 경과\n원인은 현장 확인 필요",photoIds:$photos,unknowns:["원인"],
              facts:[{text:"물자국을 관찰하고 닦았으나 다시 보임",sourceType:"USER_STATEMENT",photoIds:$photos,
                      recordIds:[$record],performanceReservationIds:[]}]}')
    fi
    save_progression_report null
    publish_progression_pdf
    old_pdf=$PROGRESS_PDF_ID
    old_source=$(jq -r '.sourceRevision' <<< "$ITEM")
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    count=$(jq '.data.items | length' "$RESPONSE_FILE")
    request user PATCH "/requests/$REQUEST_ID" 200 "$(json --argjson root "$ROOT" \
        '{expectedRevision:$root.revision,context:{conditions:"비가 오지 않은 날에도 물자국이 남아 있음"}}')"
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    assert_json '(.data.items | length) == $count' '자료 보완만으로 AI 자동 재생성 안 함' --argjson count "$count"
    request user GET "/ai-jobs/$old_job" 200
    assert_json '.data.stale == true and .data.result == null' '보완 전 AI 보고서 초안 무효화'
    request user GET "/work-items/$ITEM_ID/report" 200
    assert_json '.data.reviewStatus == "NEEDS_UPDATE"' '보완 후 보고서 갱신 필요 표시'
    report_revision=$(jq '.data.revision' "$RESPONSE_FILE")
    request user PUT "/work-items/$ITEM_ID/report" 409 "$(json --argjson revision "$report_revision" \
        --arg source "$old_source" --argjson report "$PROGRESS_REPORT" \
        '{expectedRevision:$revision,sourceRevision:$source,report:$report}')"
    assert_error STALE_SOURCE
    request user GET "/pdf-jobs/$old_pdf/content" 409
    PROGRESS_REPORT=$(jq -c '.markdown += "\n사용자 정정: 비가 오지 않은 날에도 물자국이 남아 있음"' <<< "$PROGRESS_REPORT")
    save_progression_report "$report_revision"
    publish_progression_pdf
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    assert_json '(.data.items | length) == $count' '직접 정정·재전달은 추가 AI 호출 없이 가능' --argjson count "$count"
    submit_item_ai REPORT_DRAFT
    assert_json '.data.stale == false' '사용자가 명시적으로 요청한 최신 근거 재생성'
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    assert_json '(.data.items | length) == ($count + 1)' '명시한 재생성 요청 한 건만 추가' --argjson count "$count"
    request user POST /deletion-jobs 202 "$(json --arg id "$REQUEST_ID" \
        '{targetType:"REQUEST",targetId:$id,includeAllReferences:true}')"
    AI_JOB_ID=$(value '.data.jobId')
    poll_job "/deletion-jobs/$AI_JOB_ID" COMPLETED
}
