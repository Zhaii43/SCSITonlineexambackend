from django.contrib.auth.models import AbstractUser
from django.db import models
import secrets
from datetime import timedelta
from django.utils import timezone

class User(AbstractUser):
    ROLE_CHOICES = [
        ('student', 'Student'),
        ('instructor', 'Instructor'),
        ('dean', 'Dean'),
        ('edp', 'EDP'),
    ]

    ACCOUNT_SOURCE_CHOICES = [
        ('self_registration', 'Self Registration'),
        ('masterlist_import', 'Masterlist Import'),
    ]
    
    DEPARTMENT_CHOICES = [
        ('BSHM', 'Hospitality Management'),
        ('BSIT', 'Information Technology'),
        ('BSEE', 'Electrical Engineering'),
        ('BSBA', 'Business Administration'),
        ('BSCRIM', 'Criminology'),
        ('BSED', 'Education'),
        ('BSCE', 'Civil Engineering'),
        ('BSChE', 'Chemical Engineering'),
        ('BSME', 'Mechanical Engineering'),
        ('GENERAL', 'General Education'),
    ]
    
    YEAR_LEVEL_CHOICES = [
        ('1', '1st Year'),
        ('2', '2nd Year'),
        ('3', '3rd Year'),
        ('4', '4th Year'),
    ]
    
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    department = models.CharField(max_length=10, choices=DEPARTMENT_CHOICES, default='GENERAL')

    # Student/Instructor ID
    school_id = models.CharField(max_length=20, unique=True, blank=True, null=True, help_text="Student ID or Employee ID")
    account_source = models.CharField(max_length=30, choices=ACCOUNT_SOURCE_CHOICES, default='self_registration')
    course = models.CharField(max_length=120, blank=True)
    enrolled_subjects = models.JSONField(default=list, blank=True)
    
    # Additional fields
    year_level = models.CharField(max_length=1, choices=YEAR_LEVEL_CHOICES, blank=True, null=True)
    contact_number = models.CharField(max_length=15, blank=True, null=True, unique=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    id_photo = models.ImageField(upload_to='id_photos/', blank=True, null=True)
    study_load = models.FileField(upload_to='study_loads/', blank=True, null=True, help_text="Student's study load document")
    
    # Approval system
    is_approved = models.BooleanField(default=False, help_text="Admin approval for instructors")
    approved_by = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name='approved_users')
    approved_at = models.DateTimeField(blank=True, null=True)

    # Expo push notification token
    expo_push_token = models.CharField(max_length=255, blank=True, null=True)

    # ID verification
    id_verified = models.BooleanField(default=False)
    id_verified_by = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name='id_verified_users')
    id_verified_at = models.DateTimeField(blank=True, null=True)

    # Special student types
    is_transferee = models.BooleanField(default=False)
    is_irregular = models.BooleanField(default=False)
    declaration_verified = models.BooleanField(default=False)
    declaration_verified_by = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name='declaration_verified_users')
    declaration_verified_at = models.DateTimeField(blank=True, null=True)
    extra_approved = models.BooleanField(default=False)
    extra_approved_by = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name='extra_approved_users')
    extra_approved_at = models.DateTimeField(blank=True, null=True)
    
    # Rejection reason
    rejection_reason = models.TextField(blank=True, null=True, help_text="Reason for account rejection")

    # Rejection status
    is_rejected = models.BooleanField(default=False, help_text="Whether the student registration was rejected")

    # Force password change on next login (masterlist imports)
    force_password_change = models.BooleanField(default=False)

    
    def save(self, *args, **kwargs):
        # Self-registered students require dean approval.
        # Masterlist-imported students are auto-approved by the import flow.
        if not self.pk and self.role == 'student' and self.account_source != 'masterlist_import':
            self.is_approved = False
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.username} - {self.role} ({self.school_id})"


class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    EXPIRY_MINUTES = 15  # matches email copy and expected OTP-style reset flow

    def save(self, *args, **kwargs):
        if not self.token:
            import random
            self.token = f"{random.randint(0, 999999):06d}"
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=self.EXPIRY_MINUTES)
        super().save(*args, **kwargs)

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    class Meta:
        db_table = 'password_reset_tokens'


class EmailChangeOTP(models.Model):
    """OTP for verifying email changes for authenticated users."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_change_otps')
    new_email = models.EmailField()
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.code:
            import random
            self.code = f"{random.randint(0, 999999):06d}"
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    class Meta:
        db_table = 'email_change_otps'



class EnrolledStudent(models.Model):
    """Official enrollment records added by admin — used by deans to verify student registrations."""
    DEPARTMENT_CHOICES = [
        ('BSHM', 'Hospitality Management'),
        ('BSIT', 'Information Technology'),
        ('BSEE', 'Electrical Engineering'),
        ('BSBA', 'Business Administration'),
        ('BSCRIM', 'Criminology'),
        ('BSED', 'Education'),
        ('BSCE', 'Civil Engineering'),
        ('BSChE', 'Chemical Engineering'),
        ('BSME', 'Mechanical Engineering'),
    ]
    YEAR_LEVEL_CHOICES = [
        ('1', '1st Year'), ('2', '2nd Year'), ('3', '3rd Year'), ('4', '4th Year'),
    ]

    school_id = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    department = models.CharField(max_length=10, choices=DEPARTMENT_CHOICES)
    year_level = models.CharField(max_length=1, choices=YEAR_LEVEL_CHOICES)
    course = models.CharField(max_length=120, blank=True)
    enrolled_subjects = models.JSONField(default=list, blank=True)
    email = models.EmailField(blank=True, null=True)
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.school_id} — {self.first_name} {self.last_name} ({self.department})"

    class Meta:
        db_table = 'enrolled_students'


class MasterlistImportRun(models.Model):
    STATUS_CHOICES = [
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('completed_with_warnings', 'Completed With Warnings'),
        ('failed', 'Failed'),
    ]

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='masterlist_import_runs',
    )
    department = models.CharField(max_length=10, blank=True)
    filename = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='processing')
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    email_total = models.PositiveIntegerField(default=0)
    email_sent = models.PositiveIntegerField(default=0)
    email_failed = models.PositiveIntegerField(default=0)
    email_pending = models.PositiveIntegerField(default=0)
    row_errors = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'masterlist_import_runs'
        ordering = ['-created_at']

    def __str__(self):
        return f"Import #{self.id} ({self.department}) - {self.status}"


class MasterlistImportEmailStatus(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]

    import_run = models.ForeignKey(
        MasterlistImportRun,
        on_delete=models.CASCADE,
        related_name='email_statuses',
    )
    school_id = models.CharField(max_length=20, blank=True)
    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'masterlist_import_email_statuses'
        ordering = ['id']

    def __str__(self):
        return f"{self.email} - {self.status}"
        ordering = ['department', 'last_name']


class SubjectAssignment(models.Model):
    """Dean-managed mapping between instructors and the subjects they can handle."""

    instructor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subject_assignments')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_subject_assignments')
    department = models.CharField(max_length=10, choices=User.DEPARTMENT_CHOICES)
    subject_name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subject_assignments'
        ordering = ['department', 'subject_name']
        constraints = [
            models.UniqueConstraint(fields=['instructor', 'department', 'subject_name'], name='unique_instructor_subject_assignment')
        ]

    def __str__(self):
        return f"{self.instructor.username} - {self.subject_name} ({self.department})"


class PreRegistrationOTP(models.Model):
    """Stores OTP for email verification BEFORE a user account is created."""
    email = models.EmailField()
    code = models.CharField(max_length=6)
    token = models.CharField(max_length=64, blank=True, default='')  # returned after successful verify
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.code:
            import random
            self.code = f"{random.randint(0, 999999):06d}"
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def is_valid(self):
        return not self.is_verified and timezone.now() < self.expires_at

    class Meta:
        db_table = 'pre_registration_otps'
