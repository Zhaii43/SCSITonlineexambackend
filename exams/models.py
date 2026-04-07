from django.db import models
from django.utils import timezone
from django.db.models.signals import post_delete
from django.dispatch import receiver
from datetime import timedelta
from user.models import User
from .utils import safe_delete_field

class Exam(models.Model):
    EXAM_TYPE_CHOICES = [
        ('prelim', 'Prelim'),
        ('midterm', 'Midterm'),
        ('semifinal', 'Semi-Final'),
        ('final', 'Final'),
        ('quiz', 'Quiz'),
        ('practice', 'Practice'),
    ]

    QUESTION_TYPE_CHOICES = [
        ('multiple_choice', 'Multiple Choice'),
        ('identification', 'Identification'),
        ('enumeration', 'Enumeration'),
        ('essay', 'Essay'),
        ('mixed', 'Mixed'),
    ]

    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('missed', 'Missed'),
    ]

    RETAKE_POLICY_CHOICES = [
        ('none', 'No Retakes'),
        ('best_score', 'Keep Best Score'),
        ('latest_score', 'Keep Latest Score'),
        ('average_score', 'Average All Attempts'),
    ]

    title = models.CharField(max_length=255)
    subject = models.CharField(max_length=100)
    department = models.CharField(max_length=10)
    year_level = models.CharField(max_length=50)
    exam_type = models.CharField(max_length=10, choices=EXAM_TYPE_CHOICES)
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES, default='multiple_choice')
    scheduled_date = models.DateTimeField()
    expiration_time = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.IntegerField()
    total_points = models.IntegerField()
    passing_score = models.IntegerField()
    instructions = models.TextField()
    preview_rules = models.TextField(blank=True, null=True)
    sample_questions = models.JSONField(blank=True, null=True)
    max_attempts = models.IntegerField(default=1)
    retake_policy = models.CharField(max_length=20, choices=RETAKE_POLICY_CHOICES, default='none')
    question_pool_size = models.IntegerField(default=0, help_text='Questions per student. 0 = all questions.')
    shuffle_options = models.BooleanField(default=True, help_text='Shuffle multiple choice options per student.')
    is_approved = models.BooleanField(default=False)
    is_practice = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=True, help_text='True until questions are successfully saved. Draft exams are not visible to students or the approval queue.')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_exams')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_exams')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_status(self):
        from datetime import datetime
        now = datetime.now()
        exam_end = self.expiration_time if self.expiration_time else self.scheduled_date + timedelta(minutes=self.duration_minutes)
        if now < self.scheduled_date:
            return 'upcoming'
        elif self.scheduled_date <= now <= exam_end:
            return 'ongoing'
        elif now > exam_end:
            return 'completed'
        return 'upcoming'

    def is_expired(self):
        from datetime import datetime
        if self.expiration_time:
            return datetime.now() > self.expiration_time
        exam_end = self.scheduled_date + timedelta(minutes=self.duration_minutes)
        return datetime.now() > exam_end

    class Meta:
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"{self.title} - {self.subject}"


class Question(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    question = models.TextField()
    type = models.CharField(max_length=20)
    options = models.JSONField(null=True, blank=True)
    correct_answer = models.TextField()
    points = models.IntegerField()
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.exam.title} - Q{self.order}"


class ExamResult(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='results')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_results')
    score_before_penalty = models.IntegerField(default=0)
    score = models.IntegerField()
    total_points = models.IntegerField()
    percentage = models.FloatField()
    grade = models.CharField(max_length=5)
    remarks = models.CharField(max_length=20)
    answers = models.JSONField(default=dict)
    attempt_number = models.IntegerField(default=1)
    penalty_percent = models.IntegerField(default=0)
    is_graded = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = []
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.student.username} - {self.exam.title}: {self.grade}"

    def save(self, *args, **kwargs):
        self.percentage = round((self.score / self.total_points) * 100, 2) if self.total_points and self.total_points > 0 else 0
        if self.percentage >= 97:
            self.grade = "1.00"
        elif self.percentage >= 94:
            self.grade = "1.25"
        elif self.percentage >= 91:
            self.grade = "1.50"
        elif self.percentage >= 88:
            self.grade = "1.75"
        elif self.percentage >= 85:
            self.grade = "2.00"
        elif self.percentage >= 82:
            self.grade = "2.25"
        elif self.percentage >= 79:
            self.grade = "2.50"
        elif self.percentage >= 76:
            self.grade = "2.75"
        elif self.percentage >= 75:
            self.grade = "3.00"
        else:
            self.grade = "5.00"
        self.remarks = "Passed" if float(self.grade) <= 3.0 else "Failed"
        super().save(*args, **kwargs)


class PracticeExamResult(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='practice_results')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='practice_results')
    score = models.FloatField(default=0)
    total_points = models.FloatField(default=0)
    percentage = models.FloatField(default=0)
    answers = models.JSONField(default=dict)
    results = models.JSONField(default=list)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.student.username} - {self.exam.title} (Practice)"


class CheatingViolation(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='violations')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='violations')
    violation_type = models.CharField(max_length=50)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.student.username} - {self.exam.title} - {self.violation_type}"


class ExamTermination(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='terminations')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_terminations')
    termination_count = models.IntegerField(default=1)
    is_blocked = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['exam', 'student']
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.student.username} - {self.exam.title} - Terminations: {self.termination_count}"


class ExamTimeExtension(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='time_extensions')
    student = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='time_extensions')
    extra_minutes = models.IntegerField()
    reason = models.CharField(max_length=255, blank=True)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='granted_extensions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        target = self.student.username if self.student else 'ALL'
        return f"{self.exam.title} +{self.extra_minutes}m → {target}"


class QuestionBank(models.Model):
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='question_bank')
    question = models.TextField()
    type = models.CharField(max_length=20)
    options = models.JSONField(null=True, blank=True)
    correct_answer = models.TextField()
    points = models.IntegerField(default=1)
    subject = models.CharField(max_length=100, blank=True)
    tags = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.created_by.username} - {self.question[:60]}"


class StudentExamSeed(models.Model):
    """Stores each student's unique shuffled question order for an exam."""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='seeds')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_seeds')
    question_ids = models.JSONField()  # ordered list of question PKs for this student
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['exam', 'student']

    def __str__(self):
        return f"{self.student.username} - {self.exam.title} seed"


class ExamSession(models.Model):
    """Tracks active exam sessions to prevent multi-device access"""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='sessions')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_sessions')
    session_token = models.CharField(max_length=64, unique=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['exam', 'student']
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.student.username} - {self.exam.title} ({'active' if self.is_active else 'ended'})"

    def save(self, *args, **kwargs):
        if not self.session_token:
            import secrets
            self.session_token = secrets.token_hex(32)
        super().save(*args, **kwargs)


class ExamPhoto(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='photos')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='exam_photos')
    photo = models.ImageField(upload_to='exam_photos/', null=True, blank=True)
    capture_type = models.CharField(max_length=20, choices=[
        ('start', 'Exam Start'),
        ('periodic', 'Periodic Check'),
        ('violation', 'Violation Detected'),
        ('suspicious', 'Suspicious Activity')
    ])
    violation_reason = models.CharField(max_length=100, null=True, blank=True)
    text_summary = models.TextField(null=True, blank=True)
    is_text_only = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.student.username} - {self.exam.title} - {self.capture_type} - {self.timestamp}"


class QuestionIssueReport(models.Model):
    ISSUE_TYPE_CHOICES = [
        ('missing_choice', 'Correct answer not in choices'),
        ('unclear_question', 'Question is unclear'),
        ('typo', 'Typo or formatting issue'),
        ('missing_asset', 'Missing image or asset'),
        ('grading_concern', 'Grading concern'),
        ('other', 'Other'),
    ]

    STATUS_CHOICES = [
        ('under_review', 'Under Review'),
        ('resolved', 'Resolved'),
        ('rejected', 'Rejected'),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='issue_reports')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='issue_reports')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='issue_reports')
    exam_result = models.ForeignKey(ExamResult, on_delete=models.SET_NULL, null=True, blank=True, related_name='issue_reports')
    issue_type = models.CharField(max_length=30, choices=ISSUE_TYPE_CHOICES)
    description = models.TextField()
    reported_answer = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='under_review')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']

    def __str__(self):
        return f"{self.exam.title} - Q{self.question.order} - {self.student.username}"


class QuestionIssueMessage(models.Model):
    report = models.ForeignKey(QuestionIssueReport, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='issue_report_messages')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Report #{self.report_id} - {self.sender.username}"


@receiver(post_delete, sender=ExamPhoto)
def _exam_photo_cleanup(sender, instance, **kwargs):
    safe_delete_field(instance.photo)
