#!/usr/bin/env bash
# 선택 경로와 실제 일정 제약은 API 스모크와 분리하여 업무 시나리오에서 실행한다.

choice_cancel_reservation() {
    request user GET "/reservations/$RESERVATION_ID" 200
    request user POST "/reservations/$RESERVATION_ID/cancellation" 200 "$(jq -c '
        {agreementVersion:.data.agreement.agreementVersion,reason:"E2E 선택 경로 검증 종료"}' "$RESPONSE_FILE")"
    assert_json '.data.status == "CANCELLED"' '선택 경로 예약 정리'
}

choice_set_path() {
    local selected=$1
    refresh_request
    request user PATCH "/work-items/$ITEM_ID" 200 "$(json --argjson item "$ITEM" --arg path "$selected" '
        {expectedRevision:$item.revision,resolutionPath:$path}')"
}

choice_outcome() {
    local selected=$1 outcome=$2
    request user POST "/work-items/$ITEM_ID/outcomes" 201 "$(json --arg path "$selected" --arg result "$outcome" '
        {outcome:{path:$path,result:$result,action:"E2E 가상 상태 확인",
        description:"사용자가 기록한 모의 조치 결과",photoIds:[]}}')"
    assert_json '.data.sourceType == "USER_STATEMENT" and .data.outcome.result == $result' \
        '외부 조치 결과는 사용자 진술로 저장' --arg result "$outcome"
}

choice_close_resolved() {
    refresh_request
    request user POST "/requests/$REQUEST_ID/closure" 200 "$(json --argjson root "$ROOT" '
        {expectedRevision:$root.revision,items:[$root.workItems[] | {workItemId:.workItemId,resolved:true}]}')"
    assert_json '.data.status == "CLOSED" and all(.data.workItems[]; .status == "RESOLVED")' \
        '자가·외부 해결 결과 확인 후 접수 종료'
}

check_optional_paths() {
    # 기존 시나리오 상태는 보존하며 new_request의 전역 정리 목록에는 그대로 등록한다.
    local REQUEST_ID ITEM_ID PHOTO_ID MEDIA_ID ROOT ITEM METADATA
    local TECH_ID=$TECH_ID CONSULTATION_ID DELIVERY_ID DELIVERY QUOTE_ID QUOTE RESERVATION_ID RESERVATION
    local baseline profile_revision schedule_revision main_tech=$TECH_ID

    request user GET '/consultations?limit=100' 200
    baseline=$(jq -c '[.data.items[].consultationId] | sort' "$RESPONSE_FILE")
    request anonymous GET "/public/technicians/$main_tech" 200
    assert_json '.data.directContactAvailable and .data.visitAvailability == "UNKNOWN"
        and any(.data.contacts[]; .value == "010-0000-0000")' '비로그인 공개 연락처와 방문 미확정 구분'
    request anonymous GET '/auth/me' 401
    request user GET '/consultations?limit=100' 200
    assert_json '([.data.items[].consultationId] | sort) == $before' \
        '공개 연락처 조회로 상담 관계를 만들지 않음' --argjson before "$baseline"
    request user GET '/reservations?status=CONFIRMED&limit=100' 200
    assert_json '.data.items | length == 0' '직접 연락 안내는 앱 예약을 만들지 않음'
    request anonymous GET "/public/technicians?field=PLUMBING&regionId=$(config_value '.emptyRegionId')&limit=100" 200
    assert_json '.data.items | length == 0' '연락할 기사가 없는 지역'
    request anonymous GET '/public/guidance?type=EMERGENCY' 200
    assert_json '.data.officialService.status == "AVAILABLE"
        and any(.data.officialService.routes[]; .contact == $url and .source.verified)' \
        '기사 부재 시 검증된 긴급 대안 안내' --arg url "$(config_value '.guidance.emergencyUrl')"

    new_request
    prepare_item
    choice_set_path SELF_HELP
    request user GET "/work-items/$ITEM_ID/solutions" 200
    assert_json '(.data.availablePaths | index("SELF_HELP") != null)
        and any(.data.selfHelp.guides[]; .guideId == $id and .source.verified
            and (.steps | length > 0) and (.warnings | length > 0) and (.stopConditions | length > 0))' \
        '자가 해결 적용 조건·절차·주의·중단 기준' --arg id "$(config_value '.guidance.guideId')"
    choice_outcome SELF_HELP RESOLVED
    choice_close_resolved
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    assert_json '.data.items | length == 0' '자가 해결은 AI 호출 없이 종료 가능'

    # 별도 기사에는 사례를 등록하지 않아 시연 사례 부재 조건을 재현한다.
    request technician POST /auth/login 200 "$(config_value '.accounts.noCaseTechnician | tojson')"
    request technician PATCH /auth/role 200 '{"role":"TECHNICIAN"}'
    request technician GET /technicians/me 200
    TECH_ID=$(value '.data.technicianId')
    profile_revision=$(value '.data.profileRevision')
    request technician PUT /technicians/me/profile 200 "$(json --arg revision "$profile_revision" --argjson region "$REGION" '
        {expectedRevision:$revision,profile:{displayName:"E2E 사례 없는 기사",fields:["PLUMBING"],
        regionIds:[$region.regionId],representativeMediaIds:[],contacts:[]}}')"
    request technician GET "/technicians/me/schedule?from=$(jq -r '.from' <<< "$TIMES")&to=$(jq -r '.to' <<< "$TIMES")" 200
    schedule_revision=$(value '.data.revision')
    request technician PUT /technicians/me/schedule 200 "$(json --arg revision "$schedule_revision" --argjson times "$TIMES" '
        {expectedRevision:$revision,from:$times.from,to:$times.to,availability:$times.availability,externalVisits:[]}')"
    request user GET "/technicians/$TECH_ID/portfolio" 200
    assert_json '.data.cases | length == 0' '추천·예약 대상 기사의 사례가 실제로 없음'

    new_request
    prepare_item
    choice_set_path SELF_HELP
    choice_outcome SELF_HELP UNRESOLVED
    local original_request=$REQUEST_ID original_photo=$PHOTO_ID
    prepare_item
    assert_json '.data.requestId == $id and any(.data.photos.unknownDatePhotos[]; .photoId == $photo)' \
        '자가 해결 실패 후 같은 요청과 사진을 보존' --arg id "$original_request" --arg photo "$original_photo"
    request user GET "/work-items/$ITEM_ID/general-candidates?limit=100" 200
    assert_json 'any(.data.items[]; .technician.technicianId == $tech and .timeFit == "MATCHED"
        and (has("score") | not) and (has("caseRecommendations") | not))' \
        '사례 없는 일반 후보는 사례 점수 없이 추천' --arg tech "$TECH_ID"
    create_consultation
    issue_quote
    reserve
    request user GET "/requests/$REQUEST_ID/ai-jobs?limit=100" 200
    assert_json '.data.items | length == 0' 'AI 미선택으로 상담·견적·예약 완료'
    choice_outcome DIRECT_CONTACT UNRESOLVED
    request user GET "/reservations/$RESERVATION_ID" 200
    assert_json '.data.status == "CONFIRMED"' '외부 연락 결과만으로 활성 예약을 종료하지 않음'
    request user GET "/consultations/$CONSULTATION_ID" 200
    assert_json '.data.status == "ACCEPTED"' '외부 연락 결과만으로 활성 상담을 종료하지 않음'
    choice_cancel_reservation
    # 다음 시나리오의 단일 후보 조건에 영향을 주지 않도록 활동 지역을 해제한다.
    request technician GET /technicians/me 200
    request technician PUT /technicians/me/profile 200 "$(jq -c '
        {expectedRevision:.data.profileRevision,profile:(.data.profile | .regionIds=[])}' "$RESPONSE_FILE")"
    login technician
    request technician PATCH /auth/role 200 '{"role":"TECHNICIAN"}'
    TECH_ID=$main_tech

    new_request
    prepare_item
    refresh_request
    request user PATCH "/work-items/$ITEM_ID" 200 "$(json --argjson item "$ITEM" \
        --arg manufacturer "$(config_value '.guidance.manufacturer')" '
        {expectedRevision:$item.revision,resolutionPath:"MANUFACTURER_AS",
         facts:{product:{manufacturer:$manufacturer,modelName:null,productType:null}}}')"
    request user GET "/work-items/$ITEM_ID/solutions" 200
    assert_json '.data.selectedPath == "MANUFACTURER_AS" and .data.officialService.status == "AVAILABLE"
        and any(.data.officialService.routes[]; .contact == $url and .productSpecific and .source.verified)' \
        '제품 정보를 입력한 제조사 공식 지원 경로' --arg url "$(config_value '.guidance.officialUrl')"
    choice_outcome MANUFACTURER_AS RESOLVED
    choice_close_resolved
}

choice_set_neighbor_schedule() {
    local visits=$1
    request technician GET "/technicians/me/schedule?from=$(jq -r '.from' <<< "$TIMES")&to=$(jq -r '.to' <<< "$TIMES")" 200
    request technician PUT /technicians/me/schedule 200 "$(json --arg revision "$(value '.data.revision')" \
        --argjson times "$TIMES" --argjson visits "$visits" '
        {expectedRevision:$revision,from:$times.from,to:$times.to,
         availability:$times.availability,externalVisits:$visits}')"
}

choice_check_cross_technician_overlap() {
    local REQUEST_ID=$REQUEST_ID ITEM_ID PHOTO_ID=$PHOTO_ID ROOT ITEM
    local TECH_ID=$TECH_ID CONSULTATION_ID DELIVERY_ID DELIVERY QUOTE_ID QUOTE RESERVATION_ID RESERVATION
    local existing_reservation=$1
    request user GET "/requests/$REQUEST_ID" 200
    ROOT=$(data)
    request user POST "/requests/$REQUEST_ID/work-items" 201 "$(json --argjson root "$ROOT" --arg work "$WORK_TYPE" '
        {expectedRevision:$root.revision,facts:{part:"별도 수전",workType:$work,quantity:1,fields:["PLUMBING"],
         product:{productType:null,manufacturer:null,modelName:null}}}')"
    ITEM_ID=$(value '.data.workItemId')
    request user POST "/requests/$REQUEST_ID/photos" 201 '' \
        --form "files=@\"$PHOTO_PATH\";filename=other-item.png;type=image/png" \
        --form-string "metadata=$(json --arg item "$ITEM_ID" '
            [{capturedOn:null,dateConfirmed:false,description:"별도 작업 항목 사진",workItemIds:[$item]}]')"
    PHOTO_ID=$(jq -er --arg item "$ITEM_ID" '
        .data.unknownDatePhotos[] | select(.workItemIds | index($item)) | .photoId' "$RESPONSE_FILE")
    prepare_item
    request technician POST /auth/login 200 "$(config_value '.accounts.noCaseTechnician | tojson')"
    request technician PATCH /auth/role 200 '{"role":"TECHNICIAN"}'
    request technician GET /technicians/me 200
    TECH_ID=$(value '.data.technicianId')
    request technician PUT /technicians/me/profile 200 "$(jq -c --argjson region "$REGION" '
        {expectedRevision:.data.profileRevision,profile:(.data.profile | .regionIds=[$region.regionId])}' "$RESPONSE_FILE")"
    create_consultation
    issue_quote
    request user POST /reservation-checks 200 "$(json --arg quote "$QUOTE_ID" '{operation:"CREATE",quoteId:$quote}')"
    assert_json '.data.allowed and .data.overlapConfirmationRequired and (.data.overlapConfirmed | not)
        and any(.data.overlaps[]; .reservationId == $reservation)' \
        '같은 요청의 다른 항목에 다른 기사가 방문하면 사용자 중복 확인 필요' --arg reservation "$existing_reservation"
    request user POST "/work-items/$ITEM_ID/reservations" 409 "$(json --argjson quote "$QUOTE" --argjson root "$ROOT" '
        {quoteId:$quote.quoteId,versions:$quote.terms.versions,visitDetailsRevision:$root.visitDetailsRevision}')"
    assert_error OVERLAP_CONFIRMATION_REQUIRED
    reserve
    choice_cancel_reservation
    request technician GET /technicians/me 200
    request technician PUT /technicians/me/profile 200 "$(jq -c '
        {expectedRevision:.data.profileRevision,profile:(.data.profile | .regionIds=[])}' "$RESPONSE_FILE")"
    login technician
    request technician PATCH /auth/role 200 '{"role":"TECHNICIAN"}'
}

check_route_constraints() {
    local REQUEST_ID ITEM_ID PHOTO_ID MEDIA_ID ROOT ITEM METADATA
    local CONSULTATION_ID DELIVERY_ID DELIVERY QUOTE_ID QUOTE RESERVATION_ID RESERVATION
    local TIMES=$TIMES neighbors visits first_request first_item first_quote first_root first_photo
    neighbors=$(config_value '.neighborLocations | tojson')
    TIMES=$(jq -c '.preference.ranges = [{startAt:.start,endAt:(.start | fromdateiso8601 | .+3600 | todateiso8601)}]' <<< "$TIMES")
    visits=$(json --argjson times "$TIMES" --argjson neighbors "$neighbors" '
        ($times.start | fromdateiso8601) as $start |
        [{externalVisitId:null,range:{startAt:($start-3600|todateiso8601),endAt:($start-900|todateiso8601)},
          locationId:$neighbors.before,description:"E2E 인근 선행 방문"},
         {externalVisitId:null,range:{startAt:($start+4500|todateiso8601),endAt:($start+8100|todateiso8601)},
          locationId:$neighbors.after,description:"E2E 인근 후행 방문"}]')
    choice_set_neighbor_schedule "$visits"
    assert_json '.data.externalVisits | length == 2' '앞뒤 인근 방문 일정 등록'
    new_request
    prepare_item
    refresh_request
    request user PUT "/work-items/$ITEM_ID/route-exploration" 200 "$(json --argjson item "$ITEM" '
        {expectedRevision:$item.revision,enabled:true,confirmed:true}')"
    request technician GET "/technicians/me/route-candidates?date=$(jq -r '.date' <<< "$TIMES")&limit=100" 200
    assert_json 'any(.data.items[]; (.candidateId | startswith($item+".")) and .timeFit == "MATCHED"
        and .route.beforeLocationId == $neighbors.before and .route.afterLocationId == $neighbors.after
        and .route.beforeToRequestMinutes == 5 and .route.requestToAfterMinutes == 5
        and .route.beforeToAfterMinutes == 10 and .route.additionalMinutes == 0)' \
        '앞뒤 방문 사이에 추가 이동 없이 삽입되는 요청' --arg item "$ITEM_ID" --argjson neighbors "$neighbors"
    create_consultation
    issue_quote
    assert_json '.data.price.beforeTotal == 100000 and .data.price.afterTotal == 90000
        and .data.price.discountAmount == 10000 and .data.terms.cost.discountCondition != null' \
        '동선 삽입 후보의 기사 할인 제안과 금액 조건'
    first_request=$REQUEST_ID first_item=$ITEM_ID first_quote=$QUOTE first_root=$ROOT first_photo=$PHOTO_ID

    # 두 요청이 비어 있는 같은 시간에 견적을 받은 뒤 하나만 먼저 확정한다.
    new_request
    prepare_item
    create_consultation
    issue_quote
    local competing_item=$ITEM_ID competing_quote=$QUOTE competing_root=$ROOT competing_consultation=$CONSULTATION_ID
    REQUEST_ID=$first_request ITEM_ID=$first_item QUOTE=$first_quote ROOT=$first_root PHOTO_ID=$first_photo
    QUOTE_ID=$(jq -r '.quoteId' <<< "$QUOTE")
    reserve
    local first_reservation=$RESERVATION_ID
    request user POST /reservation-checks 200 "$(json --argjson quote "$competing_quote" '{operation:"CREATE",quoteId:$quote.quoteId}')"
    assert_json '.data.allowed == false and any(.data.checks[]; .code == "TECHNICIAN_CONFLICT")' \
        '다른 요청이라도 같은 기사의 일정 충돌은 거절'
    request user POST "/work-items/$competing_item/reservations" 409 "$(json --argjson quote "$competing_quote" --argjson root "$competing_root" '
        {quoteId:$quote.quoteId,versions:$quote.terms.versions,visitDetailsRevision:$root.visitDetailsRevision}')"
    assert_error TECHNICIAN_CONFLICT
    choice_check_cross_technician_overlap "$first_reservation"
    RESERVATION_ID=$first_reservation
    choice_cancel_reservation

    # 작업 시간은 겹치지 않아도 앞뒤 이동시간이 모자라면 후보에서 제외한다.
    visits=$(jq -c --argjson times "$TIMES" '.[0].range.endAt = $times.start' <<< "$visits")
    choice_set_neighbor_schedule "$visits"
    confirm_item
    request user GET "/work-items/$first_item/general-candidates?limit=100" 200
    assert_json 'any(.data.items[]; .technician.technicianId == $tech and .timeFit == "NOT_MATCHED")' \
        '작업 시간이 겹치지 않아도 이동시간 부족이면 예약 후보 부적합' --arg tech "$TECH_ID"
    request user GET "/consultations/$competing_consultation" 200
    request user PATCH "/consultations/$competing_consultation" 200 "$(jq -c '
        {expectedRevision:.data.revision,action:"CLOSE",reason:"E2E 충돌 검증 종료"}' "$RESPONSE_FILE")"
    choice_set_neighbor_schedule '[]'
}
