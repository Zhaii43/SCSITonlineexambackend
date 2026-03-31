from django.db import models
from user.models import User

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('exam_created', 'Exam Created'),
        ('exam_approved', 'Exam Approved'),
        ('exam_rejected', 'Exam Rejected'),
        ('exam_started', 'Exam Started'),
        ('exam_taken', 'Exam Taken'),
        ('exam_terminated', 'Exam Terminated'),
        ('exam_submitted', 'Exam Submitted'),
        ('student_approved', 'Student Approved'),
        ('student_rejected', 'Student Rejected'),
        ('profile_updated', 'Profile Updated'),
        ('password_changed', 'Password Changed'),
        ('password_reset_requested', 'Password Reset Requested'),
        ('password_reset', 'Password Reset'),
        ('documents_uploaded', 'Documents Uploaded'),
        ('bulk_import_students', 'Bulk Import Students'),
        ('bulk_approve_students', 'Bulk Approve Students'),
        ('exam_time_extended', 'Exam Time Extended'),
        ('exam_time_extended_bulk', 'Exam Time Extended Bulk'),
        ('results_published', 'Results Published'),
        ('registration_resubmitted', 'Registration Resubmitted'),
        ('email_change_requested', 'Email Change Requested'),
        ('email_changed', 'Email Changed'),
        ('student_school_id_updated', 'Student School ID Updated'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.action} - {self.timestamp}"
