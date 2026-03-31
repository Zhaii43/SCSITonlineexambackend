from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from exams.models import ExamPhoto
from exams.utils import safe_delete_field


class Command(BaseCommand):
    help = "One-time cleanup for old periodic exam photos and optional orphaned files."

    def add_arguments(self, parser):
        parser.add_argument("--max-count", type=int, default=50,
                            help="Keep at most this many periodic photos per exam/student.")
        parser.add_argument("--max-days", type=int, default=7,
                            help="Keep periodic photos newer than this many days.")
        parser.add_argument("--apply", action="store_true",
                            help="Actually delete files/rows. Omit for dry-run.")
        parser.add_argument("--orphaned", action="store_true",
                            help="Also delete files in media/exam_photos with no DB row.")

    def handle(self, *args, **options):
        max_count = max(1, int(options["max_count"]))
        max_days = max(1, int(options["max_days"]))
        apply_changes = bool(options["apply"])
        cleanup_orphaned = bool(options["orphaned"])

        cutoff = timezone.now() - timedelta(days=max_days)
        periodic = (
            ExamPhoto.objects
            .filter(capture_type="periodic", photo__isnull=False)
            .order_by("exam_id", "student_id", "-timestamp", "-id")
            .only("id", "exam_id", "student_id", "timestamp", "photo")
        )

        groups = defaultdict(list)
        for photo in periodic:
            groups[(photo.exam_id, photo.student_id)].append(photo)

        total_candidates = 0
        deleted_rows = 0
        deleted_files = 0
        failed_deletes = 0

        for _, photos in groups.items():
            for idx, photo in enumerate(photos):
                if photo.timestamp < cutoff or idx >= max_count:
                    total_candidates += 1
                    if not apply_changes:
                        continue
                    try:
                        if safe_delete_field(photo.photo):
                            deleted_files += 1
                        photo.delete()
                        deleted_rows += 1
                    except Exception:
                        failed_deletes += 1

        self.stdout.write(
            f"Periodic cleanup candidates: {total_candidates} "
            f"(apply={apply_changes}, deleted_rows={deleted_rows}, "
            f"deleted_files={deleted_files}, failed={failed_deletes})"
        )

        if not cleanup_orphaned:
            return

        media_root = Path(getattr(settings, "MEDIA_ROOT", ""))
        exam_photos_dir = media_root / "exam_photos"
        if not exam_photos_dir.exists():
            self.stdout.write("No media/exam_photos directory found; skipping orphan cleanup.")
            return

        db_paths = set(
            p.replace("\\", "/")
            for p in ExamPhoto.objects.values_list("photo", flat=True)
            if p
        )

        orphan_candidates = []
        for path in exam_photos_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(media_root).as_posix()
            if rel not in db_paths:
                orphan_candidates.append(path)

        deleted_orphans = 0
        failed_orphans = 0
        if apply_changes:
            for path in orphan_candidates:
                try:
                    path.unlink()
                    deleted_orphans += 1
                except Exception:
                    failed_orphans += 1

        self.stdout.write(
            f"Orphaned file candidates: {len(orphan_candidates)} "
            f"(apply={apply_changes}, deleted={deleted_orphans}, failed={failed_orphans})"
        )
