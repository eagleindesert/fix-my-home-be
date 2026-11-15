#!/usr/bin/env bash
# 모든 업무 상태 변경은 공개된 /v1 API를 통해 진행한다.

check_public_and_sessions() {
    if [[ ${LOCAL:-false} == true ]]; then
        check_signup
    fi
    if [[ ${SKIP_HEALTH:-false} == true ]]; then
        printf 'SKIP GET /health/live: 외부 접근이 제한된 상태 확인 API\n'
        printf 'SKIP GET /health/ready: 외부 접근이 제한된 상태 확인 API\n'
    else
        request anonymous GET /health/live 200
        assert_json '.status == "live"' '프로세스 상태'
        request anonymous GET /health/ready 200
        assert_json '.status == "ready"' 'DB 및 migration 상태'
    fi
    request anonymous GET /docs 200
    [[ -s $RESPONSE_FILE ]] || die 'Swagger UI 응답이 비어 있습니다.'
    request anonymous GET /docs/oauth2-redirect 200
    request anonymous GET /public/service-info 200
    assert_json '.data.fields | index("PLUMBING") != null' '서비스 지원 분야'
    request anonymous GET '/public/guidance?type=EMERGENCY' 200
    request anonymous GET '/public/guidance?type=MANUFACTURER_AS' 200
    assert_json '.data.officialService.status == "INFORMATION_REQUIRED"' '제조사 미입력 안내'
    request anonymous GET /requests 401
    assert_error AUTHENTICATION_REQUIRED
    request anonymous POST /auth/login 401 '{"loginId":"e2e-invalid-login","password":"invalid"}'
    assert_error INVALID_CREDENTIALS

    login user
    request user GET /auth/me 200
    assert_json '.data.activeRole == "USER"' '사용자 세션'
    login other
    login technician
    local user_id other_id technician_id
    user_id=$(jq -er '.accountId' <<< "$SESSION_USER")
    other_id=$(jq -er '.accountId' <<< "$SESSION_OTHER")
    technician_id=$(jq -er '.accountId' <<< "$SESSION_TECHNICIAN")
    [[ $user_id != "$other_id" && $user_id != "$technician_id" && $other_id != "$technician_id" ]] || \
        die '권한 분리 검증에는 서로 다른 사용자·다른 사용자·기사 계정 3개가 필요합니다.'
    if [[ -n ${FAILED_DELETION_ID:-} ]]; then
        request user GET "/deletion-jobs/$FAILED_DELETION_ID" 200
        assert_json '.data.status == "FAILED" and .data.error.retryable == true' '삭제 재시도 사전 자료 확인'
    fi
    request technician PATCH /auth/role 200 '{"role":"TECHNICIAN"}'
    assert_json '.data.activeRole == "TECHNICIAN"' '기사 역할 전환'
    if jq -e '.availableRoles | index("TECHNICIAN") != null' <<< "$SESSION_USER" >/dev/null; then
        request user PATCH /auth/role 200 '{"role":"TECHNICIAN"}'
        assert_json '.data.activeRole == "TECHNICIAN"' '보유한 기사 역할 전환'
        request user PATCH /auth/role 200 '{"role":"USER"}'
        assert_json '.data.activeRole == "USER"' '사용자 역할 복귀'
    else
        request user PATCH /auth/role 403 '{"role":"TECHNICIAN"}'
        assert_error ROLE_FORBIDDEN
    fi
    request user POST /auth/logout 403 '' --header 'Origin: https://untrusted.example'
    assert_error ORIGIN_FORBIDDEN
    request user GET /auth/me 200
}

prepare_technician() {
    # 계획 시각은 UTC 15분 단위, 조회 날짜는 서울 날짜로 계산한다.
    TIMES=$(json 'now / 900 | floor | . * 900 | . as $base |
        {start:($base+7200|todateiso8601), expires:($base+5400|todateiso8601),
         changedStart:($base+8100|todateiso8601), changedEnd:($base+11700|todateiso8601),
         early:($base|todateiso8601), extendedEnd:($base+12600|todateiso8601),
         from:($base-7200+32400|strftime("%Y-%m-%d")),
         to:($base+43200+32400|strftime("%Y-%m-%d")),
         date:($base+7200+32400|strftime("%Y-%m-%d")),
         availability:[{startAt:($base-7200|todateiso8601), endAt:($base+43200|todateiso8601)}],
         preference:{mode:"FLEXIBLE", fixedStartAt:null,
                     ranges:[{startAt:($base+3600|todateiso8601), endAt:($base+21600|todateiso8601)}]}}')
    request technician GET /technicians/me 200
    TECH_ID=$(value '.data.technicianId')
    local revision source photo_ids from to schedule_revision
    revision=$(value '.data.profileRevision')
    from=$(jq -r '.from' <<< "$TIMES")
    to=$(jq -r '.to' <<< "$TIMES")
    request technician GET "/technicians/me/schedule?from=$from&to=$to" 200
    schedule_revision=$(value '.data.revision')
    assert_json '.data.departureLocationId == $location and .data.returnLocationId == $location' \
        '기사 대표 위치 사전 자료' --arg location "$LOCATION_ID"
    source=$(config_value '.source | tojson')
    request technician POST /technicians/me/portfolio-photos 201 '' \
        --form "files=@\"$PHOTO_PATH\";filename=e2e.png;type=image/png" --form-string "source=$source"
    assert_json '.data | length == 1' '포트폴리오 사진 업로드'
    photo_ids=$(jq -c '[.data[].mediaId]' "$RESPONSE_FILE")
    request technician PUT /technicians/me/profile 200 "$(json --arg revision "$revision" \
        --argjson region "$REGION" --argjson ids "$photo_ids" '
        {expectedRevision:$revision, profile:{displayName:"E2E 가상 기사", fields:["PLUMBING"],
         regionIds:[$region.regionId], representativeMediaIds:$ids,
         contacts:[{contact:{label:"테스트 연락처",value:"010-0000-0000"},isPublic:true}]}}')"
    find_page_item anonymous "/public/technicians?field=PLUMBING&regionId=$(jq -r '.regionId' <<< "$REGION")&limit=100" \
        '.technicianId == $tech' '공개 기사 검색' --arg tech "$TECH_ID"
    request anonymous GET "/public/technicians/$TECH_ID" 200
    assert_json '.data.displayName == "E2E 가상 기사"' '공개 프로필 수정 반영'
    request user GET "/technicians/$TECH_ID/portfolio" 200
    request technician POST /technicians/me/cases 201 "$(jq -c '{case:.case}' "$CONFIG")"
    CASE_ID=$(value '.data.caseId')
    revision=$(value '.data.revision')
    request technician PATCH "/technicians/me/cases/$CASE_ID" 200 "$(jq -c --arg revision "$revision" \
        '{expectedRevision:$revision, case:.updatedCase}' "$CONFIG")"
    request user GET "/cases/$CASE_ID" 200
    assert_json '(.data.content | del(.source)) == ($expected | del(.source))' \
        '사례 변경 반영' --argjson expected "$(config_value '.updatedCase | tojson')"

    request technician PUT /technicians/me/schedule 200 "$(json --arg revision "$schedule_revision" \
        --argjson times "$TIMES" '{expectedRevision:$revision, from:$times.from, to:$times.to,
        availability:$times.availability, externalVisits:[]}')"
    assert_json '.data.availability | length > 0' '기사 일정 저장'
}

new_request() {
    METADATA=$(json --argjson region "$REGION" \
        '{symptom:"E2E 싱크대 수전 누수 관찰", region:$region,
          photos:[{capturedOn:null,dateConfirmed:false,description:"E2E 가상 사진"}]}')
    request user POST /requests 201 '' \
        --form "files=@\"$PHOTO_PATH\";filename=e2e.png;type=image/png" --form-string "metadata=$METADATA"
    ROOT=$(data)
    REQUEST_ID=$(value '.data.requestId')
    ITEM_ID=$(value '.data.workItems[0].workItemId')
    PHOTO_ID=$(value '.data.photos.unknownDatePhotos[0].photoId')
    MEDIA_ID=$(value '.data.photos.unknownDatePhotos[0].media.mediaId')
    ITEM=$(jq -c '.workItems[0]' <<< "$ROOT")
}

edit_request_and_records() {
    IDEMPOTENCY_KEY="$RUN_ID-create-request" new_request
    IDEMPOTENCY_KEY="$RUN_ID-create-request" request user POST /requests 201 '' \
        --form "files=@\"$PHOTO_PATH\";filename=e2e.png;type=image/png" --form-string "metadata=$METADATA"
    assert_json ".data.requestId == \"$REQUEST_ID\"" '동일 멱등 키 재전송'
    IDEMPOTENCY_KEY="$RUN_ID-create-request" request user POST /requests 409 '' \
        --form "files=@\"$PHOTO_PATH\";filename=e2e.png;type=image/png" \
        --form-string "metadata=$(jq -c '.symptom="다른 요청"' <<< "$METADATA")"
    assert_error IDEMPOTENCY_KEY_REUSED
    request other GET "/requests/$REQUEST_ID" 403
    assert_error ACCESS_DENIED
    request other GET "/media/$MEDIA_ID" 403
    assert_error ACCESS_DENIED
    request user GET "/media/$MEDIA_ID" 200
    [[ -s $RESPONSE_FILE ]] || die '원본 이미지가 비어 있습니다.'
    request anonymous GET "/media/$MEDIA_ID" 401
    request user GET '/requests?limit=0' 422
    assert_error VALIDATION_ERROR
    request user GET '/requests?limit=1&limit=2' 400
    assert_error BAD_REQUEST

    refresh_request
    local old_revision
    old_revision=$(jq -r '.revision' <<< "$ROOT")
    request user PATCH "/requests/$REQUEST_ID" 200 "$(json --arg revision "$old_revision" \
        '{expectedRevision:$revision,symptom:"E2E 누수 관찰 및 기록 보완"}')"
    request user PATCH "/requests/$REQUEST_ID" 409 "$(json --arg revision "$old_revision" \
        '{expectedRevision:$revision,symptom:"오래된 편집"}')"
    assert_error VERSION_CONFLICT
    request user POST "/requests/$REQUEST_ID/photos" 201 '' \
        --form "files=@\"$PHOTO_PATH\";filename=second.png;type=image/png" \
        --form-string 'metadata=[{"capturedOn":null,"dateConfirmed":false,"description":"두 번째 사진"}]'
    assert_json '.data.remainingCount == 28' '사진 슬롯 차감'
    refresh_request
    local photo record_body
    photo=$(jq -c --arg id "$PHOTO_ID" '.photos.unknownDatePhotos[] | select(.photoId == $id)' <<< "$ROOT")
    request user PUT "/photos/$PHOTO_ID" 200 '' \
        --form "file=@\"$PHOTO_PATH\";filename=replaced.png;type=image/png" \
        --form-string "expectedRevision=$(jq -r '.revision' <<< "$photo")" \
        --form-string "metadata=$(json --arg item "$ITEM_ID" \
        '{capturedOn:null,dateConfirmed:false,description:"E2E 사진 정정",workItemIds:[$item]}')"
    MEDIA_ID=$(value '.data.media.mediaId')
    assert_json '.data.description == "E2E 사진 정정"' '사진 메타정보 정정'
    record_body=$(json --arg item "$ITEM_ID" --arg photo "$PHOTO_ID" \
        '{record:{description:"E2E 관찰 기록",photoIds:[$photo],workItemIds:[$item]}}')
    request user POST "/requests/$REQUEST_ID/records" 201 "$record_body"
    RECORD_ID=$(value '.data.recordId')
    request user PATCH "/records/$RECORD_ID" 200 "$(jq -c \
        '{expectedRevision:.data.revision,record:(.data.record | .description="E2E 보완 기록")}' "$RESPONSE_FILE")"
    assert_json '.data.record.description == "E2E 보완 기록"' '기록 정정'
    request user POST "/work-items/$ITEM_ID/outcomes" 201 "$(json --arg photo "$PHOTO_ID" \
        '{outcome:{path:"DIRECT_CONTACT",result:"UNRESOLVED",action:"E2E 문의",
        description:"현장 확인 필요",photoIds:[$photo]}}')"
    refresh_request
    request user POST "/requests/$REQUEST_ID/work-items" 201 "$(json --argjson root "$ROOT" \
        '{expectedRevision:$root.revision,facts:{part:"추가 수전",workType:"가상 점검",quantity:1,
        fields:["PLUMBING"],product:{productType:null,manufacturer:null,modelName:null}}}')"
    refresh_request
    request user PUT "/requests/$REQUEST_ID/photo-groups" 200 "$(json --argjson root "$ROOT" \
        '{sourceRevision:$root.sourceRevision,groups:[{label:"E2E 수전",
          photoIds:[$root.photos.unknownDatePhotos[].photoId],
          selectedPhotoIds:[$root.photos.unknownDatePhotos[].photoId]}]}')"
    request user GET "/requests/$REQUEST_ID/timeline" 200
    assert_json '.data.groups | length == 1' '사진 묶음과 타임라인'
}

check_ai() {
    refresh_request
    request user POST "/requests/$REQUEST_ID/ai-jobs" 202 "$(json --argjson item "$ITEM" \
        '{type:"DIAGNOSIS",sourceRevision:$item.sourceRevision,workItemId:$item.workItemId}')"
    local job_id
    job_id=$(value '.data.jobId')
    poll_job "/ai-jobs/$job_id" "$AI_STATUS"
    if [[ $AI_STATUS == SUCCEEDED ]]; then
        assert_json '.data.result.summary != null and .data.stale == false and .data.error == null' 'AI 결과와 근거 유효성'
    else
        assert_json '.data.error.code == $code and .data.result == null' \
            '명시적으로 지정한 AI 실패 처리' --arg code "$(config_value '.ai.expectedErrorCode')"
    fi
    request user GET "/requests/$REQUEST_ID/ai-jobs?type=DIAGNOSIS&limit=1" 200
    assert_json ".data.items[0].jobId == \"$job_id\"" 'AI 작업 목록'
    refresh_request
    assert_json '.data.workItems[0].reviewStatus != "CONFIRMED"' 'AI가 사용자 확인을 대신하지 않음'
    request user PUT "/requests/$REQUEST_ID/ai-dialogue" 200 "$(json --argjson root "$ROOT" \
        '{expectedRevision:$root.dialogue.revision,action:"FINISH"}')"
    assert_json '.data.finished == true' 'AI 문답 종료'
}

prepare_item() {
    refresh_request
    request user PATCH "/work-items/$ITEM_ID" 200 "$(json --argjson item "$ITEM" \
        --argjson times "$TIMES" --arg work "$WORK_TYPE" '
        {expectedRevision:$item.revision, facts:{part:"싱크대",workType:$work,quantity:1,
         fields:["PLUMBING"],visitPreference:$times.preference},resolutionPath:"TECHNICIAN"}')"
    confirm_item
    refresh_request
    request user PUT "/requests/$REQUEST_ID/visit-details" 200 "$(json --argjson root "$ROOT" \
        --argjson region "$REGION" '{expectedRevision:$root.revision,confirmed:true,
        visitDetails:{address:($region.city+" "+$region.district+" "+$region.neighborhood+" 가상 101호"),
        contact:"010-0000-0001"}}')"
    ROOT=$(data)
}

check_candidates() {
    request user GET "/work-items/$ITEM_ID/solutions" 200
    assert_json '.data.availablePaths | index("TECHNICIAN") != null' '기사 해결 경로'
    request user GET "/work-items/$ITEM_ID/case-recommendations" 200
    assert_json '.data.evaluationStatus == "NOT_REQUESTED"' '사례 AI 평가 미실행 상태'
    find_page_item user "/work-items/$ITEM_ID/general-candidates?limit=100" \
        '.technician.technicianId == $tech and .timeFit == "MATCHED"' \
        '일반 기사 추천과 일정 적합성' --arg tech "$TECH_ID"
    refresh_request
    request user PUT "/work-items/$ITEM_ID/route-exploration" 200 "$(json --argjson item "$ITEM" \
        '{expectedRevision:$item.revision,enabled:true,confirmed:true}')"
    find_page_item technician "/technicians/me/route-candidates?date=$(jq -r '.date' <<< "$TIMES")&limit=100" \
        '.candidateId | startswith($item + ".")' '동선 후보 검색' --arg item "$ITEM_ID"
    local candidate
    candidate=$(jq -er --arg item "$ITEM_ID" '.data.items[] | select(.candidateId | startswith($item+".")) | .candidateId' "$RESPONSE_FILE")
    request technician POST "/route-candidates/$candidate/interests" 201
    request user GET "/work-items/$ITEM_ID/interests" 200
    assert_json ".data | any(.candidateId == \"$candidate\")" '기사 관심 표시'
}

check_report_and_pdf() {
    refresh_request
    request user PUT "/work-items/$ITEM_ID/report" 200 "$(json --argjson item "$ITEM" --arg photo "$PHOTO_ID" \
        '{expectedRevision:null,sourceRevision:$item.sourceRevision,
          report:{markdown:"# E2E 누수 기록\n원인은 미확인입니다.",photoIds:[$photo],facts:[],unknowns:["원인"]}}')"
    request user GET "/work-items/$ITEM_ID/report" 200
    request user PUT "/work-items/$ITEM_ID/report/confirmation" 200 "$(jq -c \
        '{expectedRevision:.data.revision,sourceRevision:.data.sourceRevision,confirmed:true}' "$RESPONSE_FILE")"
    assert_json '.data.reviewStatus == "CONFIRMED" and .data.current != null' '보고서 확인'
    create_delivery EXTERNAL_PDF true
    EXTERNAL_DELIVERY_ID=$DELIVERY_ID
    local media
    media=$(jq -r '.content.photos[0].media.mediaId' <<< "$DELIVERY")
    request user GET "/media/$media" 200
    [[ -s $RESPONSE_FILE ]] || die '마스킹 이미지가 비어 있습니다.'
    request user GET "/work-items/$ITEM_ID/deliveries?purpose=EXTERNAL_PDF&status=READY&limit=1" 200
    assert_json ".data.items[0].deliveryId == \"$DELIVERY_ID\"" '전달본 목록 필터'
    request user POST "/deliveries/$DELIVERY_ID/pdf-jobs" 202 "$(json --argjson delivery "$DELIVERY" \
        '{deliveryRevision:$delivery.revision}')"
    PDF_ID=$(value '.data.jobId')
    poll_job "/pdf-jobs/$PDF_ID" READY
    assert_json '.data.downloadAvailable == true' 'PDF 다운로드 가능 상태'
    request user GET "/deliveries/$DELIVERY_ID/pdf-jobs?status=READY&limit=1" 200
    assert_json ".data.items[0].jobId == \"$PDF_ID\"" 'PDF 목록'
    request user GET "/pdf-jobs/$PDF_ID/content" 200
    [[ $(head -c 5 "$RESPONSE_FILE") == '%PDF-' ]] || die 'PDF 파일 시그니처 오류'
    grep -Eiq '^content-type: application/pdf' "$HEADER_FILE" || die 'PDF Content-Type 오류'
    request other GET "/pdf-jobs/$PDF_ID/content" 403
    assert_error ACCESS_DENIED
}

create_consultation() {
    create_delivery CONSULTATION false
    request user POST "/work-items/$ITEM_ID/consultations" 201 "$(json --arg tech "$TECH_ID" \
        --arg delivery "$DELIVERY_ID" '{technicianId:$tech,deliveryId:$delivery}')"
    CONSULTATION_ID=$(value '.data.consultationId')
    request technician GET "/consultations/$CONSULTATION_ID" 200
    assert_json '.data.status == "PENDING" and .data.quoteContext != null' '상담 요청과 공유 전제'
    request technician PATCH "/consultations/$CONSULTATION_ID" 200 "$(jq -c \
        '{expectedRevision:.data.revision,action:"ACCEPT"}' "$RESPONSE_FILE")"
    assert_json '.data.status == "ACCEPTED"' '기사 상담 수락'
    find_page_item user '/consultations?status=ACCEPTED&limit=100' \
        '.consultationId == $id' '사용자 상담 목록' --arg id "$CONSULTATION_ID"
    find_page_item technician '/consultations?status=ACCEPTED&limit=100' \
        '.consultationId == $id' '기사 상담 목록' --arg id "$CONSULTATION_ID"
    request technician GET "/deliveries/$DELIVERY_ID" 200
    request technician GET "/requests/$REQUEST_ID" 403
    assert_error ROLE_FORBIDDEN
}

issue_quote() {
    refresh_request
    request technician POST "/consultations/$CONSULTATION_ID/quotes" 201 "$(json \
        --argjson root "$ROOT" --argjson item "$ITEM" --argjson times "$TIMES" \
        --arg delivery "$DELIVERY_ID" '{contextDeliveryId:$delivery,terms:{
        versions:{commonVersion:$root.commonVersion,itemVersion:$item.itemVersion,proposalVersion:null},
        fields:["PLUMBING"],scope:"E2E 수전 교체",quantity:1,durationMinutes:60,
        startAt:$times.start,expiresAt:$times.expires,
        cost:{minimumVisitFee:0,minimumDiagnosticFee:0,discountCondition:"E2E 시간 합의",
        lines:[{category:"LABOR",description:"가상 작업비",confirmed:true,
                beforeAmount:100000,afterAmount:90000,condition:null}]}}}')"
    QUOTE=$(data)
    QUOTE_ID=$(value '.data.quoteId')
    assert_json '.data.selectable == true and .data.price.afterTotal == 90000' '선택 가능한 견적과 합계'
}

reserve() {
    request user POST /reservation-checks 200 "$(json --arg id "$QUOTE_ID" '{operation:"CREATE",quoteId:$id}')"
    assert_json '.data.allowed == true' '예약 확정 전 검사'
    local check_id body
    check_id=$(value '.data.checkId')
    request user PUT "/reservation-checks/$check_id/confirmation" 200 '{"confirmed":true}'
    assert_json '.data.overlapConfirmed == true' '예약 검사 확인'
    body=$(json --argjson root "$ROOT" --argjson quote "$QUOTE" \
        '{quoteId:$quote.quoteId,versions:$quote.terms.versions,visitDetailsRevision:$root.visitDetailsRevision}')
    IDEMPOTENCY_KEY="$RUN_ID-reserve-$ITEM_ID" request user POST "/work-items/$ITEM_ID/reservations" 201 "$body"
    RESERVATION=$(data)
    RESERVATION_ID=$(value '.data.reservationId')
    IDEMPOTENCY_KEY="$RUN_ID-reserve-$ITEM_ID" request user POST "/work-items/$ITEM_ID/reservations" 201 "$body"
    assert_json ".data.reservationId == \"$RESERVATION_ID\" and .data.status == \"CONFIRMED\"" '예약 재전송 중복 방지'
    find_page_item user '/reservations?status=CONFIRMED&limit=100' \
        '.reservationId == $id' '사용자 예약 목록' --arg id "$RESERVATION_ID"
    find_page_item technician '/reservations?status=CONFIRMED&limit=100' \
        '.reservationId == $id' '기사 예약 목록' --arg id "$RESERVATION_ID"
    request technician GET "/reservations/$RESERVATION_ID" 200
    assert_json '.data.agreement.terms.visitDetails.contact == "010-0000-0001"' '활성 예약 기사 방문 정보'
}

change_and_perform_work() {
    local path="/reservations/$RESERVATION_ID" old_agreement change_id version
    old_agreement=$(jq -r '.agreement.agreementVersion' <<< "$RESERVATION")
    request technician PUT "$path/preparation-notes" 200 \
        '{"preparation":{"equipment":["E2E 렌치"],"parts":[],"inspectionItems":["연결부"],"note":"가상 방문 준비"}}'
    assert_json '.data.equipment == ["E2E 렌치"]' '방문 준비 기록'
    request user POST "$path/changes" 201 "$(json --argjson reservation "$RESERVATION" \
        --argjson times "$TIMES" '{type:"BEFORE_START",agreementVersion:$reservation.agreement.agreementVersion,
        terms:($reservation.agreement.terms | {fields,scope,quantity,cost,visitPreference}
        + {scope:"E2E 수전 및 연결부 점검",startAt:$times.changedStart,expectedEndAt:$times.changedEnd})}')"
    change_id=$(value '.data.changeId')
    assert_json '.data.userAccepted == true and .data.technicianAccepted == false' '변경 제안 단독 수락 상태'
    request technician PATCH "/reservation-changes/$change_id" 200 "$(jq -c \
        '{expectedRevision:.data.revision,action:"ACCEPT"}' "$RESPONSE_FILE")"
    assert_json '.data.status == "APPLIED"' '양측 수락 후 변경 반영'
    request user POST "$path/cancellation" 409 "$(json --arg version "$old_agreement" '{agreementVersion:$version}')"
    assert_error VERSION_CONFLICT
    request user GET "$path" 200
    RESERVATION=$(data)
    version=$(value '.data.agreement.agreementVersion')
    assert_json '.data.agreementHistory | length == 2' '합의 이력'
    request technician POST "$path/work-events" 409 "$(json --arg version "$version" \
        '{event:"START",agreementVersion:$version}')"
    assert_error EARLY_START_CONSENT_REQUIRED
    request user PUT "$path/early-start-consent" 200 "$(json --arg version "$version" --argjson times "$TIMES" \
        '{agreementVersion:$version,expectedConsentRevision:null,action:"GRANT",proposedStartAt:$times.early}')"
    assert_json '.data.earlyStartConsent.active == true' '조기 시작 동의'
    request technician POST "$path/work-events" 200 "$(json --arg version "$version" \
        '{event:"START",agreementVersion:$version}')"
    assert_json '.data.status == "IN_PROGRESS" and .data.actualStartedAt != null' '실제 작업 시작'
    request technician POST "$path/work-events" 200 "$(jq -c --argjson times "$TIMES" \
        '{event:"UPDATE_EXPECTED_END",agreementVersion:.data.agreement.agreementVersion,
          expectedEndEstimateRevision:.data.endEstimateRevision,expectedEndAt:$times.extendedEnd}' "$RESPONSE_FILE")"
    assert_json '.data.endEstimateSource == "OPERATIONS"' '실제 종료 예상 변경'
    request user POST "$path/work-events" 200 "$(json --arg version "$version" \
        '{event:"REQUEST_STOP",agreementVersion:$version,reason:"E2E 사용자 중단 요청"}')"
    assert_json '.data.status == "STOP_REQUESTED"' '사용자 중단 요청'
    local performance
    performance='{"confirmedCause":null,"performed":["가상 점검"],"notPerformed":["교체"],"unknowns":["원인"],"parts":[],"endLocationId":null}'
    request technician POST "$path/work-events" 409 "$(json --arg version "$version" --argjson performance "$performance" \
        '{event:"COMPLETE",agreementVersion:$version,performance:$performance}')"
    assert_error INVALID_STATE
    request technician POST "$path/work-events" 200 "$(json --arg version "$version" --argjson performance "$performance" \
        '{event:"STOP",agreementVersion:$version,performance:$performance}')"
    assert_json '.data.status == "STOPPED" and .data.agreement.terms.visitDetails == null' '종료 상태와 방문 정보 비공개'
    request technician PUT "$path/end-location" 200 "$(jq -c --arg location "$LOCATION_ID" \
        '{expectedEndLocationRevision:.data.endLocationRevision,endLocationId:$location}' "$RESPONSE_FILE")"
    assert_json ".data.performance.endLocationId == \"$LOCATION_ID\"" '종료 위치 정정'
    request technician GET "/deliveries/$DELIVERY_ID" 403
    assert_error ACCESS_DENIED
    request user GET "/pdf-jobs/$PDF_ID" 200
    assert_json '.data.downloadAvailable == false' '근거 변경 후 PDF 다운로드 차단'
    request user GET "/pdf-jobs/$PDF_ID/content" 409
}

check_cancellation() {
    new_request
    CANCEL_REQUEST_ID=$REQUEST_ID
    prepare_item
    create_consultation
    issue_quote
    reserve
    request user POST "/reservations/$RESERVATION_ID/cancellation" 200 "$(json \
        --argjson reservation "$RESERVATION" '{agreementVersion:$reservation.agreement.agreementVersion,reason:"E2E 취소"}')"
    assert_json '.data.status == "CANCELLED"' '예약 취소'
    request technician GET "/reservations/$RESERVATION_ID" 200
    assert_json '.data.agreement.terms.visitDetails == null' '취소 후 방문 정보 비공개'
    request user GET '/requests?limit=1' 200
    local cursor first_id
    cursor=$(value '.data.nextCursor')
    first_id=$(value '.data.items[0].requestId')
    cursor=$(jq -rn --arg cursor "$cursor" '$cursor | @uri')
    request user GET "/requests?limit=1&cursor=$cursor" 200
    assert_json ".data.items | length == 1 and .[0].requestId != \"$first_id\"" '커서 다음 페이지 중복 방지'
}

close_and_delete() {
    local target job_id
    local -a completed_job_ids=()
    REQUEST_ID=$MAIN_REQUEST_ID ITEM_ID=$MAIN_ITEM_ID
    refresh_request
    request user POST "/requests/$REQUEST_ID/closure" 200 "$(json --argjson root "$ROOT" \
        '{expectedRevision:$root.revision,items:[$root.workItems[] |
          {workItemId:.workItemId,resolved:false,reason:"E2E 검증 완료"}]}')"
    assert_json '.data.status == "CLOSED"' '전체 요청 종료'
    for target in "$MAIN_REQUEST_ID" "$CANCEL_REQUEST_ID"; do
        request user POST /deletion-jobs 202 "$(json --arg target "$target" \
            '{targetType:"REQUEST",targetId:$target,includeAllReferences:true}')"
        job_id=$(value '.data.jobId')
        completed_job_ids+=("$job_id")
        assert_json '.data.accessBlocked == true' '삭제 접수 즉시 접근 차단'
        request user GET "/requests/$target" 404
        assert_error RESOURCE_NOT_FOUND
        poll_job "/deletion-jobs/$job_id" COMPLETED
        assert_json '.data.error == null and .data.restoredPhotoSlots > 0' '파생 자료 및 파일 삭제 완료'
    done
    request user POST "/deletion-jobs/$job_id/retry" 409
    assert_error INVALID_STATE
    if [[ -n ${FAILED_DELETION_ID:-} ]]; then
        request user GET "/deletion-jobs/$FAILED_DELETION_ID" 200
        assert_json '.data.status == "FAILED" and .data.error.retryable == true' '삭제 재시도 선행 상태'
        request user POST "/deletion-jobs/$FAILED_DELETION_ID/retry" 202
        poll_job "/deletion-jobs/$FAILED_DELETION_ID" COMPLETED
        assert_json '.data.error == null and .data.restoredPhotoSlots == 1' '실패한 삭제 작업 복구'
    else
        printf 'SKIP 삭제 재시도 성공 경로: failedDeletionJobId 미지정 (완료 작업 재시도 거부는 검증)\n'
    fi
    for job_id in "${completed_job_ids[@]}"; do
        find_page_item user '/deletion-jobs?status=COMPLETED&targetType=REQUEST&limit=100' \
            '.jobId == $id' '이번 실행에서 완료된 삭제 작업 목록' --arg id "$job_id"
    done
    request user GET '/requests?limit=100' 200
    assert_json 'all(.data.items[]; .requestId != $main and .requestId != $cancel)' \
        '이번 실행 요청 정리 완료' --arg main "$MAIN_REQUEST_ID" --arg cancel "$CANCEL_REQUEST_ID"
    for target in user other technician; do
        request "$target" POST /auth/logout 204
        request "$target" GET /auth/me 401
        assert_error AUTHENTICATION_REQUIRED
    done
}

run_scenarios() {
    check_public_and_sessions
    prepare_technician
    edit_request_and_records
    MAIN_REQUEST_ID=$REQUEST_ID MAIN_ITEM_ID=$ITEM_ID
    check_ai
    prepare_item
    check_candidates
    check_report_and_pdf
    create_consultation
    issue_quote
    request user PATCH "/quotes/$QUOTE_ID" 200 "$(json --argjson quote "$QUOTE" \
        '{expectedRevision:$quote.revision,action:"REJECT"}')"
    assert_json '.data.status == "REJECTED"' '견적 거절'
    issue_quote
    request user GET "/work-items/$ITEM_ID/quotes" 200
    assert_json '.data | length == 2' '견적 목록'
    reserve
    change_and_perform_work
    check_cancellation
    close_and_delete
}
