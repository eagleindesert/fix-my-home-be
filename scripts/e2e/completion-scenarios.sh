#!/usr/bin/env bash
# 예약 후 최신 인계 → 정상 완료 → 개인정보를 제거한 수행 이력 보존.

write_completion_report() {
    local revision=$1 record_id=${2:-}
    refresh_request
    request user PUT "/work-items/$ITEM_ID/report" 200 "$(json \
        --arg revision "$revision" --arg record "$record_id" --arg photo "$PHOTO_ID" \
        --argjson item "$ITEM" --argjson root "$ROOT" '
        {expectedRevision:(if $revision == "" then null else $revision end),
         sourceRevision:$item.sourceRevision,
         report:{markdown:("# 방문 전 인계\n수전 연결부의 누수를 관찰했습니다.\n방문 주소: "
             + $root.visitDetails.address + "\n방문 연락처: " + $root.visitDetails.contact),
           photoIds:[$photo], unknowns:["원인은 현장 확인 필요"],
           facts:(if $record == "" then [] else [{text:"물을 사용한 뒤 연결부에 물방울이 보였습니다.",
             sourceType:"USER_STATEMENT", photoIds:[$photo], recordIds:[$record],
             performanceReservationIds:[]}] end)}}')"
    request user PUT "/work-items/$ITEM_ID/report/confirmation" 200 "$(jq -c \
        '{expectedRevision:.data.revision,sourceRevision:.data.sourceRevision,confirmed:true}' "$RESPONSE_FILE")"
    assert_json '.data.reviewStatus == "CONFIRMED"' '방문 전 최신 보고서 사용자 확인'
}

create_completion_handover() {
    local record_id=${1:-} replaces=${2:-}
    refresh_request
    request user POST "/work-items/$ITEM_ID/deliveries" 202 "$(json \
        --argjson item "$ITEM" --arg tech "$TECH_ID" --arg reservation "$RESERVATION_ID" \
        --arg photo "$PHOTO_ID" --arg record "$record_id" --arg replaces "$replaces" '
        {sourceRevision:$item.sourceRevision,
         scope:{purpose:"HANDOVER",recipientTechnicianId:$tech,reservationId:$reservation,
           photoIds:[$photo],recordIds:(if $record == "" then [] else [$record] end),
           questionIds:[],includeSummary:true,includeReport:true,includeQuoteContext:false},
         redactions:[{targetType:"PHOTO",resourceId:$photo,exclude:false,boxes:[[0,0,0.5,0.5]]}]}
         + if $replaces == "" then {} else {replacesDeliveryId:$replaces} end')"
    HANDOVER_ID=$(value '.data.deliveryId')
    poll_job "/deliveries/$HANDOVER_ID" READY
    local confirmation
    confirmation=$(jq -c \
        '{expectedRevision:.data.revision,sourceRevision:.data.sourceRevision,confirmed:true}' "$RESPONSE_FILE")
    request technician GET "/deliveries/$HANDOVER_ID" 403
    assert_error ACCESS_DENIED
    request user PUT "/deliveries/$HANDOVER_ID/confirmation" 200 "$confirmation"
    request technician GET "/deliveries/$HANDOVER_ID" 200
    assert_json '.data.scope.purpose == "HANDOVER" and .data.reviewStatus == "CONFIRMED"
        and .data.content.quoteContext == null and .data.metadataRemoved' '확정 기사의 확인된 인계본 열람'
}

check_completion_and_handover() {
    # 앞선 완료·중단의 실제 종료 위치가 다음 조기 시작을 제한하므로,
    # 이 독립 요청은 기존 작업 시나리오보다 먼저 실행하고 여기에서 삭제한다.
    new_request
    local completion_request_id=$REQUEST_ID original_media=$MEDIA_ID
    prepare_item
    create_consultation
    issue_quote
    reserve
    local path="/reservations/$RESERVATION_ID" version
    version=$(jq -r '.agreement.agreementVersion' <<< "$RESERVATION")
    local address contact
    address=$(jq -r '.visitDetails.address' <<< "$ROOT")
    contact=$(jq -r '.visitDetails.contact' <<< "$ROOT")

    write_completion_report ''
    create_completion_handover
    local original_handover=$HANDOVER_ID

    # 외부 연락으로 추가 확인한 내용을 본인 접수에 보완한다. 원본 상담 대화는 저장하지 않는다.
    request user POST "/requests/$REQUEST_ID/records" 201 "$(json \
        --arg item "$ITEM_ID" --arg photo "$PHOTO_ID" '
        {record:{description:"물을 사용한 뒤 연결부에 물방울이 보였습니다.",
                 photoIds:[$photo],workItemIds:[$item]}}')"
    local selected_record
    selected_record=$(value '.data.recordId')
    request user POST "/requests/$REQUEST_ID/records" 201 "$(json --arg item "$ITEM_ID" '
        {record:{description:"공유하지 않은 개인 메모",photoIds:[],workItemIds:[$item]}}')"
    request user GET "/deliveries/$original_handover" 200
    assert_json '.data.status == "STALE" and .data.reviewStatus == "NEEDS_UPDATE"
        and .data.content == null' '접수 보완 후 이전 인계본 갱신 필요'
    request technician GET "/deliveries/$original_handover" 403
    assert_error ACCESS_DENIED
    request user GET "$path" 200
    assert_json '.data.status == "CONFIRMED"' '접수 보완이 확정 예약을 자동 종료하지 않음'

    confirm_item
    request user GET "/work-items/$ITEM_ID/report" 200
    local report_revision
    report_revision=$(value '.data.revision')
    write_completion_report "$report_revision" "$selected_record"
    create_completion_handover "$selected_record" "$original_handover"
    local latest_handover=$HANDOVER_ID masked_media
    masked_media=$(value '.data.content.photos[0].media.mediaId')
    assert_json '.data.content.records | length == 1 and .[0].recordId == $record' \
        '사용자가 선택한 보완 기록만 전달' --arg record "$selected_record"
    assert_json '.data.content.report.content.facts[0].recordIds == [$record]
        and .data.content.report.content.facts[0].photoIds == [$photo]
        and (.data.content.report.content.markdown | contains($address) and contains($contact))' \
        '최신 보고서의 사진·기록 근거와 활성 방문 정보' \
        --arg record "$selected_record" --arg photo "$PHOTO_ID" --arg address "$address" --arg contact "$contact"
    request technician GET "/media/$masked_media" 200
    [[ -s $RESPONSE_FILE ]] || die '기사 인계본 사진이 비어 있습니다.'
    request technician GET "/media/$original_media" 403
    assert_error ROLE_FORBIDDEN
    request other GET "/deliveries/$latest_handover" 403
    assert_error ACCESS_DENIED
    request technician GET "$path" 200
    assert_json '.data.handoverDeliveryIds == [$delivery]' '예약에 최신 인계본만 연결' --arg delivery "$latest_handover"
    request technician PUT "$path/preparation-notes" 200 \
        '{"preparation":{"equipment":["누수 확인 도구"],"parts":["연결부 패킹"],"inspectionItems":["수전 연결부"],"note":"사용자 확인 기록을 바탕으로 현장 점검"}}'

    request user PUT "$path/early-start-consent" 200 "$(json --arg version "$version" --argjson times "$TIMES" '
        {agreementVersion:$version,expectedConsentRevision:null,action:"GRANT",proposedStartAt:$times.early}')"
    request technician POST "$path/work-events" 200 "$(json --arg version "$version" '
        {event:"START",agreementVersion:$version}')"
    assert_json '.data.status == "IN_PROGRESS" and .data.actualStartedAt != null' '정상 완료 경로 작업 시작'
    request technician POST "$path/work-events" 200 "$(json --arg version "$version" --arg location "$LOCATION_ID" '
        {event:"COMPLETE",agreementVersion:$version,
         performance:{confirmedCause:"연결부 패킹 손상",performed:["패킹 교체","통수 후 누수 없음 확인"],
           notPerformed:[],unknowns:[],parts:["연결부 패킹"],endLocationId:$location}}')"
    assert_json '.data.status == "COMPLETED" and .data.actualEndedAt != null
        and .data.performance.confirmedCause == "연결부 패킹 손상"
        and .data.performance.performed == ["패킹 교체","통수 후 누수 없음 확인"]
        and .data.performance.parts == ["연결부 패킹"]
        and .data.agreement.terms.visitDetails == null and .data.preparation == null' \
        '정상 완료 수행 기록과 종료 후 방문 정보 비공개'
    request technician GET "/deliveries/$latest_handover" 200
    assert_json '.data.status == "READY" and .data.content.quoteContext == null
        and (.data.content | tostring | contains($address) == false and contains($contact) == false)
        and (.data.content.report.content.markdown | contains("[비공개 방문 정보]"))' \
        '종료된 기사 인계 기록의 주소·연락처 제거' --arg address "$address" --arg contact "$contact"
    request technician GET "/media/$masked_media" 200
    request other GET "/media/$masked_media" 403
    assert_error ACCESS_DENIED
    refresh_request
    assert_json '.data.workItems[0].status == "RESOLVED"
        and .data.workItems[0].activeReservationId == null' '완료한 작업 항목 해결 상태'
    request user POST "/requests/$REQUEST_ID/closure" 200 "$(json --argjson root "$ROOT" '
        {expectedRevision:$root.revision,items:[$root.workItems[] | {workItemId:.workItemId,resolved:true}]}')"
    assert_json '.data.status == "CLOSED" and (.data.closures | all(.resolved))' '해결 완료로 접수 종료'

    request user POST /deletion-jobs 202 "$(json --arg target "$completion_request_id" '
        {targetType:"REQUEST",targetId:$target,includeAllReferences:true}')"
    local deletion_id
    deletion_id=$(value '.data.jobId')
    poll_job "/deletion-jobs/$deletion_id" COMPLETED
    request technician GET "/deliveries/$latest_handover" 404
    request technician GET "/media/$masked_media" 404
    local target remaining=()
    for target in "${CREATED_REQUEST_IDS[@]}"; do
        if [[ $target != "$completion_request_id" ]]; then remaining+=("$target"); fi
    done
    CREATED_REQUEST_IDS=("${remaining[@]}")
}
