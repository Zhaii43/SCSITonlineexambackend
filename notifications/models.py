from django.db import models
from user.models import User


class Announcement(models.Model):
    TARGET_CHOICES = [
        ('all', 'Everyone'),
        ('student', 'Students Only'),
        ('instructor', 'Instructors Only'),
    ]

    YEAR_LEVEL_CHOICES = [
        ('1', '1st Year'),
        ('2', '2nd Year'),
        ('3', '3rd Year'),
        ('4', '4th Year'),
    ]

    title = models.CharField(max_length=255)
    message = models.TextField()
    target_audience = models.CharField(max_length=20, choices=TARGET_CHOICES, default='all')
    department = models.CharField(max_length=10, blank=True, null=True, help_text='Leave blank for all departments')
    year_level = models.CharField(max_length=1, choices=YEAR_LEVEL_CHOICES, blank=True, null=True, help_text='Leave blank for all year levels (students only)')
    subject_name = models.CharField(max_length=120, blank=True, null=True, help_text='Subject this announcement targets (instructor announcements)')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='announcements')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.target_audience})"


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('announcement', 'Announcement'),
        ('issue_report', 'Issue Report'),
        ('exam_approved', 'Exam Approved'),
        ('exam_scheduled', 'Exam Scheduled'),
        ('exam_reminder', 'Exam Reminder'),
        ('exam_warning', 'Exam Warning'),
        ('exam_blocked', 'Exam Blocked'),
        ('result_published', 'Result Published'),
        ('account_approved', 'Account Approved'),
        ('time_extended', 'Time Extended'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    link = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.title}"
