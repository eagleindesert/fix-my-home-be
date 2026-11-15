"""트랜잭션 안에서만 사용하는 도메인 작업 문맥."""

import copy
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db import Job, ReferenceData, Resource, StoredFile, now, uid
from app.errors import require
from app.media import FileStore
from app.security import require_actor
from app.time_rules import iso

ACTIVE_RESERVATIONS = ("CONFIRMED", "IN_PROGRESS", "STOP_REQUESTED")
ACTIVE_CONSULTATIONS = ("PENDING", "ACCEPTED")


@dataclass
class Context:
    db: object
    actor: object
    settings: object
    new_files: list = field(default_factory=list)
    obsolete_files: list = field(default_factory=list)
    path_params: dict = field(default_factory=dict)

    @property
    def files(self):
        return FileStore(self.settings.storage_dir)

    def create(self, kind, data=None, **columns):
        resource = Resource(id=uid(), kind=kind, data=copy.deepcopy(data or {}),
                            owner_id=columns.pop("owner_id", self.actor.account_id if self.actor else None),
                            **columns)
        self.db.add(resource)
        self.db.flush()
        return resource

    def save(self, resource, **values):
        resource.data = {**copy.deepcopy(resource.data), **copy.deepcopy(values)}
        resource.revision += 1
        resource.updated_at = now()
        self.db.flush()
        return resource

    def get(self, resource_id, kind=None, allow_deleting=False):
        resource = self.db.get(Resource, resource_id)
        require(resource is not None and (not kind or resource.kind == kind),
                "RESOURCE_NOT_FOUND", "자료를 찾을 수 없습니다.", 404)
        require(allow_deleting or not resource.deleting, "RESOURCE_NOT_FOUND", "자료를 찾을 수 없습니다.", 404)
        if resource.request_id and not allow_deleting:
            root = self.db.get(Resource, resource.request_id)
            require(root and not root.deleting, "RESOURCE_NOT_FOUND", "자료를 찾을 수 없습니다.", 404)
        return resource

    def own(self, resource_id, kind=None, writable=False):
        require_actor(self.actor, "USER")
        resource = self.get(resource_id, kind)
        require(resource.owner_id == self.actor.account_id, "ACCESS_DENIED", "본인 자료만 이용할 수 있습니다.", 403)
        if writable:
            self.open_request(resource)
        return resource

    def open_request(self, resource):
        root = resource if resource.kind == "REQUEST" else self.get(resource.request_id, "REQUEST")
        require(root.status == "OPEN" and not root.deleting, "RESOURCE_CLOSED", "종료된 요청입니다.")
        return root

    def party(self, resource_id, kind=None):
        require_actor(self.actor)
        resource = self.get(resource_id, kind)
        owner = self.actor.role == "USER" and resource.owner_id == self.actor.account_id
        technician = self.actor.role == "TECHNICIAN" and resource.technician_id == self.actor.technician_id
        require(owner or technician, "ACCESS_DENIED", "해당 관계의 당사자만 이용할 수 있습니다.", 403)
        return resource

    def technician(self):
        require_actor(self.actor, "TECHNICIAN")
        require(self.actor.technician_id, "ROLE_FORBIDDEN", "연결된 기사 자원이 없습니다.", 403)
        return self.get(self.actor.technician_id, "TECHNICIAN")

    def no_self(self, item, technician_id):
        technician = self.get(technician_id, "TECHNICIAN")
        require(technician.owner_id != item.owner_id, "SELF_PARTICIPATION_FORBIDDEN", "자기 요청에는 기사로 참여할 수 없습니다.", 403)
        return technician

    def check_revision(self, resource, expected):
        require(str(resource.revision) == expected, "VERSION_CONFLICT", "최신 자료를 다시 조회하세요.")

    def check_source(self, resource, expected):
        require(resource.data.get("sourceRevision") == expected, "STALE_SOURCE", "근거 자료가 변경되었습니다.")

    def find(self, kind=None, **conditions):
        query = select(Resource).where(Resource.deleting.is_(False))
        if kind:
            query = query.where(Resource.kind == kind)
        for key, value in conditions.items():
            query = query.where(getattr(Resource, key) == value)
        return list(self.db.scalars(query.order_by(Resource.created_at, Resource.id)))

    def active_relations(self, request_id=None, item_id=None):
        rows = self.find(request_id=request_id) if request_id else self.find(item_id=item_id)
        return [row for row in rows if (row.kind == "CONSULTATION" and row.status in ACTIVE_CONSULTATIONS)
                or (row.kind == "RESERVATION" and row.status in ACTIVE_RESERVATIONS)]

    def references(self, kind):
        return list(self.db.scalars(select(ReferenceData).where(
            ReferenceData.kind == kind, ReferenceData.verified.is_(True)).order_by(ReferenceData.id)))

    def validate_references(self, ids, kind, request_id, item_id=None):
        require(len(ids) == len(set(ids)), "INVALID_REFERENCE", "자료 ID가 중복되었습니다.", 422)
        result = []
        for resource_id in ids:
            resource = self.get(resource_id, kind)
            require(resource.request_id == request_id, "INVALID_REFERENCE", "다른 요청의 자료입니다.", 422)
            if item_id and resource.kind in ("PHOTO", "RECORD"):
                linked = resource.data.get("workItemIds", []) if resource.kind == "PHOTO" else resource.data["record"]["workItemIds"]
                require(not linked or item_id in linked, "INVALID_REFERENCE", "다른 항목의 사진입니다.", 422)
            result.append(resource)
        return result

    def invalidate_sources(self, root, item_ids=None):
        self.save(root, sourceRevision=uid())
        items = self.find("WORK_ITEM", request_id=root.id)
        for item in items:
            if item_ids is not None and item.id not in item_ids:
                continue
            self.save(item, sourceRevision=uid(), reviewStatus="NEEDS_UPDATE", routeExplorationEnabled=False)
            for resource in self.find(item_id=item.id):
                if resource.kind in ("REPORT", "DELIVERY", "PDF_JOB"):
                    if resource.kind != "REPORT":
                        resource.status = "STALE"
                    self.save(resource, reviewStatus="NEEDS_UPDATE")

    def invalidate_quotes(self, request_id=None, item_id=None):
        scope = {"request_id": request_id} if request_id else {"item_id": item_id}
        for quote in self.find("QUOTE", **scope):
            if quote.status == "ACTIVE":
                quote.status = "RECONFIRMATION_REQUIRED"
                self.save(quote)

    def store_file(self, resource, content, mime, width=None, height=None):
        key = self.files.write(content)
        self.new_files.append(key)
        file = StoredFile(id=uid(), resource_id=resource.id, key=key, mime=mime,
                          size=len(content), width=width, height=height)
        self.db.add(file)
        self.db.flush()
        return file

    def file_for(self, resource):
        file = self.db.scalar(select(StoredFile).where(StoredFile.resource_id == resource.id))
        require(file, "RESOURCE_NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
        return file

    def enqueue(self, resource, kind, payload, deadline=None):
        self.db.add(Job(id=resource.id, kind=kind, payload=copy.deepcopy(payload),
                        state="QUEUED", deadline_at=deadline))

    def relation_event(self, relation, action, reason=None):
        events = copy.deepcopy(relation.data.get("events", []))
        events.append({"status": action, "occurredAt": iso(now()), "reason": reason})
        self.save(relation, events=events)
