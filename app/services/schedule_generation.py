from __future__ import annotations

from app.logic import fixed_group_validation_error
from app.models import Assignment, FixedLesson, Lesson, Project, SchoolClass, Subject, Teacher
from app.scheduling.rules import (
    assignment_groups,
    assignment_requires_double,
    fixed_row_size,
    remaining_pattern_groups,
    required_double_block_state,
)
from app.scheduling.solver.api import solve, solve_missing, solve_rebuild
from app.services.entities.schemas import GenerateScheduleIn
from app.services.foundation import logger
from app.services.schedule_operations.blocks import add_generated_lessons
from app.services.schedule_operations.validation import (
    minimal_schedule_invalid_lessons,
    schedule_integrity_report,
)
from app.services.schedule_validation import schedule_input_validation_report
from app.services.schedule_diagnostics import unscheduled_assignment_details
from collections import Counter, defaultdict
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Optional
import time
from app.scheduling.solver.diagnostics import SCHEDULER_REVISION
from app.services.scheduler_diagnostics import record_scheduler_run


def generate_schedule(db: Session, p: Project, pid: int, payload: Optional[GenerateScheduleIn]):
    assignments = db.scalars(
        select(Assignment).where(Assignment.project_id == pid)
    ).all()
    classes = db.scalars(select(SchoolClass).where(SchoolClass.project_id == pid)).all()
    input_validation = schedule_input_validation_report(
        db, p, assignments=assignments, classes=classes
    )
    reference_issues = input_validation["assignment_reference_issues"]
    if reference_issues:
        labels = {"teacher_id": "giáo viên", "class_id": "lớp", "subject_id": "môn"}
        details = []
        for issue in reference_issues[:5]:
            refs = ", ".join(
                f"{labels.get(ref['field'], ref['field'])} #{ref['id']}"
                for ref in issue["invalid_refs"]
            )
            details.append(f"phân công #{issue['assignment_id']}: {refs}")
        suffix = (
            f"; và {len(reference_issues) - 5} phân công khác"
            if len(reference_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "assignment_project_mismatch",
                "assignment_reference_issues": reference_issues,
                "message": (
                    "Không thể xếp lịch vì có phân công tham chiếu giáo viên, lớp hoặc môn "
                    "không còn tồn tại hoặc thuộc project khác: "
                    + "; ".join(details)
                    + suffix
                    + ". Hãy sửa/xóa phân công lỗi trước khi xếp lại."
                ),
            },
            409,
        )
    duplicate_issues = input_validation["duplicate_assignment_issues"]
    teacher_subject_issues = input_validation["teacher_subject_issues"]
    if teacher_subject_issues:
        details = "; ".join(
            f"{item['teacher_name']} – {item['subject_name']} (phân công #{item['assignment_id']})"
            for item in teacher_subject_issues[:5]
        )
        suffix = (
            f"; và {len(teacher_subject_issues) - 5} phân công khác"
            if len(teacher_subject_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "teacher_subject_mismatch",
                "teacher_subject_issues": teacher_subject_issues,
                "message": (
                    "Không thể xếp lịch vì có giáo viên được phân công môn chưa được cấu hình chuyên môn: "
                    f"{details}{suffix}. Hãy sửa chuyên môn hoặc chuyển phân công trước khi xếp lại."
                ),
            },
            409,
        )
    if duplicate_issues:
        details = "; ".join(
            f"{item['class_name']} – {item['subject_name']} "
            f"(phân công ID {', '.join(map(str, item['assignment_ids']))})"
            for item in duplicate_issues[:5]
        )
        suffix = (
            f"; và {len(duplicate_issues) - 5} cặp khác"
            if len(duplicate_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "duplicate_assignments",
                "duplicate_assignment_issues": duplicate_issues,
                "message": (
                    "Không thể xếp lịch vì một lớp–môn đang có nhiều phân công: "
                    f"{details}{suffix}. Hãy xóa hoặc chuyển dữ liệu để mỗi lớp–môn "
                    "chỉ còn một giáo viên rồi xếp lại."
                ),
            },
            409,
        )
    curriculum_issues = [
        row for row in input_validation["grade_requirement_issues"]
        if row["issue_type"] != "missing"
    ]
    if curriculum_issues:
        details = []
        for item in curriculum_issues[:5]:
            if item["issue_type"] == "missing":
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: thiếu phân công "
                    f"{item['required_periods']} tiết/tuần"
                )
            elif item["issue_type"] == "extra":
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: môn không thuộc chương trình khối"
                )
            else:
                mode_labels = {
                    "free": "Tự do",
                    "preferred_double": "Ưu tiên tiết đôi",
                    "required_double": "Bắt buộc tiết đôi",
                }
                current_mode = mode_labels.get(
                    item["assigned_mode"], item["assigned_mode"]
                )
                required_mode = mode_labels.get(
                    item["required_mode"], item["required_mode"]
                )
                details.append(
                    f"{item['class_name']} – {item['subject_name']}: đang {item['assigned_periods']} tiết/tuần · {current_mode}, "
                    f"chương trình khối yêu cầu {item['required_periods']} tiết/tuần · {required_mode}"
                )
        suffix = (
            f"; và {len(curriculum_issues) - 5} mục khác"
            if len(curriculum_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "grade_requirements_mismatch",
                "grade_requirement_issues": curriculum_issues,
                "message": (
                    "Không thể xếp lịch vì phân công chưa khớp chương trình chuẩn theo khối: "
                    + "; ".join(details)
                    + suffix
                    + ". Hãy bổ sung, chỉnh hoặc xóa phân công dư trước khi xếp tự động."
                ),
            },
            409,
        )
    fixed_definition_issues = input_validation["fixed_definition_issues"]
    if fixed_definition_issues:
        details = "; ".join(
            item.get("message", "Dữ liệu tiết cố định không hợp lệ")
            for item in fixed_definition_issues[:5]
        )
        suffix = (
            f"; và {len(fixed_definition_issues) - 5} lỗi ghim khác"
            if len(fixed_definition_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "fixed_lesson_invalid",
                "fixed_definition_issues": fixed_definition_issues,
                "message": (
                    "Không thể xếp lịch vì dữ liệu tiết cố định không hợp lệ: "
                    f"{details}{suffix} Hãy bỏ ghim lỗi rồi cố định lại."
                ),
            },
            409,
        )

    existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()
    assignment_by_id = {assignment.id: assignment for assignment in assignments}

    # Chuẩn hóa dữ liệu cố định cũ và hỗ trợ nhiều cụm cố định trên một phân công.
    lessons_by_assignment = defaultdict(list)
    for lesson in existing:
        lessons_by_assignment[lesson.assignment_id].append(lesson)
    fixed_rows = db.scalars(
        select(FixedLesson).where(FixedLesson.project_id == pid)
    ).all()
    fixed_changed = False
    assignments_with_unsatisfied_fixed = set()
    fixed_specs_by_assignment = defaultdict(list)
    for fixed_row in fixed_rows:
        assignment = assignment_by_id.get(fixed_row.assignment_id)
        if not assignment:
            db.delete(fixed_row)
            fixed_changed = True
            continue
        size = fixed_row_size(
            p, assignment, fixed_row, lessons_by_assignment[assignment.id]
        )
        if size < 1:
            return JSONResponse(
                {
                    "ok": False,
                    "message": (
                        "Có dữ liệu tiết cố định cũ không xác định được là tiết lẻ hay cặp tiết. "
                        "Hãy bỏ ghim tại ô đó rồi cố định lại trước khi xếp lịch."
                    ),
                },
                409,
            )
        fixed_specs_by_assignment[assignment.id].append((fixed_row.slot, size))
        if fixed_row.group_size != size:
            fixed_row.group_size = size
            fixed_changed = True
        expected_slots = set(range(fixed_row.slot, fixed_row.slot + size))
        matching = {
            lesson.slot: lesson
            for lesson in lessons_by_assignment[assignment.id]
            if lesson.slot in expected_slots
        }
        if expected_slots.issubset(matching):
            for slot in expected_slots:
                if not matching[slot].locked:
                    matching[slot].locked = True
                    fixed_changed = True
        else:
            assignments_with_unsatisfied_fixed.add(assignment.id)

    for assignment_id, fixed_specs in fixed_specs_by_assignment.items():
        assignment = assignment_by_id[assignment_id]
        fixed_error = fixed_group_validation_error(
            assignment_groups(assignment),
            fixed_specs,
            days=p.days,
            sessions=p.sessions,
            periods_per_session=p.periods_per_session,
        )
        if fixed_error:
            return JSONResponse(
                {
                    "ok": False,
                    "message": f"Dữ liệu tiết cố định của phân công không hợp lệ: {fixed_error} Hãy bỏ các ghim dư/trùng rồi xếp lại.",
                },
                409,
            )

    for assignment_id in assignments_with_unsatisfied_fixed:
        for lesson in lessons_by_assignment[assignment_id]:
            if not lesson.locked:
                db.delete(lesson)
                fixed_changed = True
    if fixed_changed:
        db.flush()
        existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()

    # Rà lại lịch cũ trước mỗi lần xếp vì các ràng buộc chính thức có thể đã
    # thay đổi sau khi lịch được tạo. Nguyện vọng giáo viên chỉ để tham khảo
    # và tuyệt đối không được đọc ở đây hoặc ở solver.
    invalid_lessons = []
    rebuild_assignment_ids = set()
    for lesson in minimal_schedule_invalid_lessons(db, p, assignments, existing):
        assignment = assignment_by_id.get(lesson.assignment_id)
        if not assignment:
            invalid_lessons.append(lesson)
            continue
        if lesson.locked:
            invalid_lessons.append(lesson)
        elif assignment_requires_double(assignment):
            rebuild_assignment_ids.add(assignment.id)
        else:
            invalid_lessons.append(lesson)

    existing_by_assignment = defaultdict(list)
    for lesson in existing:
        existing_by_assignment[lesson.assignment_id].append(lesson)
    for assignment in assignments:
        lessons_for_assignment = existing_by_assignment[assignment.id]
        if not lessons_for_assignment:
            continue
        if assignment_requires_double(assignment):
            block_state = required_double_block_state(
                p, assignment, lessons_for_assignment
            )
            if not block_state["valid"]:
                rebuild_assignment_ids.add(assignment.id)
        else:
            slots_for_assignment = [lesson.slot for lesson in lessons_for_assignment]
            if remaining_pattern_groups(p, assignment, slots_for_assignment) is None:
                rebuild_assignment_ids.add(assignment.id)

    if rebuild_assignment_ids:
        # Với required_double, lỗi ở một tiết di động chỉ yêu cầu dựng lại phần
        # di động của phân công. Các tiết khóa hợp lệ phải được giữ lại; chỉ khi
        # chính tập tiết khóa không thể thuộc bất kỳ mẫu hợp lệ nào mới báo lỗi
        # cố định.
        for assignment_id in rebuild_assignment_ids:
            assignment = assignment_by_id.get(assignment_id)
            assignment_lessons = [
                lesson for lesson in existing if lesson.assignment_id == assignment_id
            ]
            locked_assignment_lessons = [
                lesson for lesson in assignment_lessons if lesson.locked
            ]
            if assignment and locked_assignment_lessons:
                if assignment_requires_double(assignment):
                    locked_state = required_double_block_state(
                        p, assignment, locked_assignment_lessons
                    )
                    if not locked_state["valid"]:
                        invalid_lessons.extend(locked_assignment_lessons)
                else:
                    locked_slots = [lesson.slot for lesson in locked_assignment_lessons]
                    if remaining_pattern_groups(p, assignment, locked_slots) is None:
                        invalid_lessons.extend(locked_assignment_lessons)
            invalid_lessons.extend(
                lesson for lesson in assignment_lessons if not lesson.locked
            )
    invalid_lessons = list({lesson.id: lesson for lesson in invalid_lessons}.values())
    locked_invalid = [lesson for lesson in invalid_lessons if lesson.locked]
    if locked_invalid:
        return JSONResponse(
            {
                "ok": False,
                "assignment_availability_issues": [
                    {"assignment_id": assignment_id, "message": "Tiết cố định xung đột với ràng buộc hoặc cấu trúc tiết đôi. Hãy kiểm tra và bỏ ghim liên quan."}
                    for assignment_id in sorted({row.assignment_id for row in locked_invalid})
                ],
                "message": f"Có {len(locked_invalid)} tiết cố định xung đột với ràng buộc hoặc chế độ xếp tiết mới. Hãy bỏ cố định hoặc điều chỉnh ràng buộc trước khi xếp lại.",
            },
            409,
        )
    for lesson in invalid_lessons:
        db.delete(lesson)
    if invalid_lessons:
        db.flush()
        existing = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()

    # Tính số tiết còn thiếu theo từng phân công, không lấy tổng toàn project.
    # Cách này vẫn đúng nếu dữ liệu cũ/import từng bị lệch giữa các phân công
    # (một phân công thừa tiết trong khi phân công khác lại thiếu).
    existing_counts = Counter(lesson.assignment_id for lesson in existing)
    excess_assignment_issues = []
    for assignment in assignments:
        existing_count = existing_counts[assignment.id]
        required_count = int(assignment.periods_per_week or 0)
        if existing_count <= required_count:
            continue
        school_class = db.get(SchoolClass, assignment.class_id)
        subject = db.get(Subject, assignment.subject_id)
        teacher = db.get(Teacher, assignment.teacher_id)
        excess_assignment_issues.append(
            {
                "assignment_id": assignment.id,
                "class_name": school_class.name
                if school_class
                else f"Lớp #{assignment.class_id}",
                "subject_name": subject.name
                if subject
                else f"Môn #{assignment.subject_id}",
                "teacher_name": teacher.name
                if teacher
                else f"GV #{assignment.teacher_id}",
                "required": required_count,
                "existing": existing_count,
                "excess": existing_count - required_count,
            }
        )
    if excess_assignment_issues:
        details = "; ".join(
            f"{item['class_name']} – {item['subject_name']} ({item['existing']}/{item['required']} tiết)"
            for item in excess_assignment_issues[:5]
        )
        suffix = (
            f"; và {len(excess_assignment_issues) - 5} phân công khác"
            if len(excess_assignment_issues) > 5
            else ""
        )
        return JSONResponse(
            {
                "ok": False,
                "reason": "excess_assignment_periods",
                "excess_assignment_issues": excess_assignment_issues,
                "message": (
                    "Không thể tiếp tục xếp lịch vì có phân công đang thừa số tiết/tuần: "
                    f"{details}{suffix}. Hãy đưa bớt tiết dư về khay rồi xếp lại."
                ),
            },
            409,
        )

    missing = sum(
        int(assignment.periods_per_week or 0) - existing_counts[assignment.id]
        for assignment in assignments
    )

    search_diagnostics = None

    def record_failed_run(outcome):
        db.rollback()
        if search_diagnostics is not None:
            try:
                record_scheduler_run(db, pid, search_diagnostics, outcome)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Could not persist failed scheduler diagnostic for project %s", pid)

    def run_solver(solver, mode, tries):
        nonlocal search_diagnostics
        started = time.monotonic()
        search_diagnostics = {
            "scheduler_revision": SCHEDULER_REVISION,
            "mode": mode,
            "initial_lessons": len(existing),
        }
        try:
            result = solver(db, p, tries=tries)
        except Exception:
            search_diagnostics["elapsed_seconds"] = round(time.monotonic() - started, 3)
            record_failed_run({"status": "error", "saved": False, "message": "Bộ xếp gặp sự cố; lịch trước thao tác được giữ lại."})
            raise
        search_diagnostics.update({
            "solver": result.get("solver"),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "result_periods": len(result["lessons"]),
            "unscheduled": result["unscheduled"],
            "optimal": result.get("optimal", False),
            "search_limited": result.get("search_limited", not result.get("optimal", False)),
            "maximum_placed": result.get("maximum_placed", result["unscheduled"] == 0),
        })
        logger.info("Schedule generation diagnostic: %s", search_diagnostics)
        return result

    def finalize_generated_schedule(
        response_payload, *, invalid_status_code: int = 500
    ):
        """Run the same authoritative integrity gate before committing."""
        db.flush()
        integrity = schedule_integrity_report(db, p, allow_partial=True)
        if not integrity["valid"]:
            logger.error(
                "Generated/current timetable failed final validation: %s",
                integrity,
            )
            record_failed_run({"status": "rejected", "saved": False, "message": "Kết quả xếp bị từ chối do không vượt qua kiểm tra toàn vẹn.", "integrity": integrity})
            return JSONResponse(
                {
                    "ok": False,
                    "reason": (
                        "schedule_integrity_failed"
                        if invalid_status_code < 500
                        else "solver_validation_failed"
                    ),
                    "message": (
                        "Thời khóa biểu hiện tại chưa vượt qua kiểm tra toàn vẹn. "
                        "Dữ liệu trước thao tác được giữ nguyên; hãy xử lý các lỗi được báo rồi thử lại."
                    ),
                    "integrity": integrity,
                },
                invalid_status_code,
            )

        remaining = unscheduled_assignment_details(
            db, p, assignments, {"lessons": []}, "missing"
        )
        missing_periods = sum(row["missing_periods"] for row in remaining)
        missing_curriculum = [
            row for row in input_validation["grade_requirement_issues"]
            if row["issue_type"] == "missing"
        ]
        current_lessons = db.scalars(select(Lesson).where(Lesson.project_id == pid)).all()
        response_payload.update(
            saved=True,
            partial=bool(missing_periods or missing_curriculum),
            scheduled=len(current_lessons),
            unscheduled=missing_periods,
            unscheduled_assignments=remaining,
            grade_requirement_issues=missing_curriculum,
            class_capacity_issues=input_validation["class_capacity_issues"],
            assignment_availability_issues=input_validation["assignment_availability_issues"],
        )
        if search_diagnostics is not None:
            response_payload["search_diagnostics"] = search_diagnostics
        if response_payload["partial"]:
            response_payload["message"] = (
                f"Đã lưu {len(current_lessons)} tiết lên thời khóa biểu; "
                f"còn {missing_periods} tiết chưa xếp trong khay."
            )
            if missing_curriculum:
                response_payload["message"] += (
                    f" Còn {len(missing_curriculum)} mục lớp–môn chưa được phân công giáo viên."
                )
            movable_ids = sorted(row.id for row in current_lessons if not row.locked)
            response_payload.update(
                can_rebuild=bool(missing_periods and movable_ids),
                affected_lesson_ids=movable_ids,
                moved_count=len(movable_ids),
            )
        if search_diagnostics is not None:
            record_scheduler_run(db, pid, search_diagnostics, {
                "status": "partial" if response_payload["partial"] else "complete",
                "saved": True,
                "scheduled": len(current_lessons),
                "unscheduled": missing_periods,
                "score": response_payload.get("score"),
                "preserved_current": response_payload.get("preserved_current", False),
                "message": response_payload["message"],
            })
        db.commit()
        return response_payload

    # Từ lần xếp thứ hai trở đi, giữ nguyên lịch khi chỉ bổ sung phần thiếu.
    # Nếu người dùng đã xác nhận rebuild, đi thẳng vào rebuild thay vì chạy lại
    # solve_missing rồi mới rebuild lần thứ hai.
    if existing:
        if missing == 0:
            return finalize_generated_schedule(
                {
                    "ok": True,
                    "score": 0,
                    "unscheduled": 0,
                    "message": "Thời khóa biểu đã đủ tiết và vượt qua kiểm tra toàn vẹn.",
                },
                invalid_status_code=409,
            )

        if payload and payload.allow_rebuild:
            current_lessons = db.scalars(
                select(Lesson).where(Lesson.project_id == pid)
            ).all()
            rebuild_lesson_ids = sorted(
                lesson.id for lesson in current_lessons if not lesson.locked
            )
            confirmed_rebuild_ids = sorted(
                set(payload.confirmed_rebuild_lesson_ids or [])
            )
            if confirmed_rebuild_ids != rebuild_lesson_ids:
                return JSONResponse(
                    {
                        "ok": False,
                        "requires_confirmation": True,
                        "moved_count": len(rebuild_lesson_ids),
                        "affected_lesson_ids": rebuild_lesson_ids,
                        "message": (
                            "Lịch đã thay đổi kể từ lần xác nhận trước. "
                            "Hệ thống cần được phép thử xếp lại tối đa "
                            f"{len(rebuild_lesson_ids)} tiết không cố định hiện tại; "
                            "các tiết cố định vẫn được giữ nguyên."
                        ),
                    },
                    409,
                )

            rebuild = run_solver(solve_rebuild, "rebuild", 260)
            if rebuild["unscheduled"] > 0 and len(rebuild["lessons"]) < len(rebuild_lesson_ids):
                return finalize_generated_schedule({
                    "ok": True, "score": rebuild["score"], "preserved_current": True,
                })

            moved_count = len(rebuild_lesson_ids)
            for lesson in current_lessons:
                if not lesson.locked:
                    db.delete(lesson)
            db.flush()
            add_generated_lessons(db, p, rebuild["lessons"])
            return finalize_generated_schedule(
                {
                    "ok": True,
                    "score": rebuild["score"],
                    "unscheduled": 0,
                    "message": (
                        f"Đã giữ nguyên các tiết cố định và xếp lại {moved_count} tiết "
                        "không cố định để hoàn thành thời khóa biểu."
                    ),
                }
            )

        result = run_solver(solve_missing, "missing", 160)
        add_generated_lessons(db, p, result["lessons"])
        return finalize_generated_schedule(
            {
                "ok": True,
                "score": result["score"],
                "unscheduled": 0,
                "message": (
                    f"Đã xếp bổ sung {len(result['lessons'])} tiết từ khay và giữ "
                    "nguyên các vị trí còn hợp lệ."
                ),
            }
        )

    # Chỉ khi lịch hoàn toàn trống mới chạy bộ xếp toàn bộ.
    result = run_solver(solve, "full", 120)
    for l in existing:
        db.delete(l)
    add_generated_lessons(db, p, result["lessons"])
    return finalize_generated_schedule(
        {
            "ok": True,
            "score": result["score"],
            "unscheduled": 0,
            "message": f"Đã xếp đầy đủ {len(result['lessons'])} tiết.",
        }
    )
