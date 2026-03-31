from django.contrib import admin
from .models import Exam, ExamResult, Question, QuestionIssueReport, QuestionIssueMessage

@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'department', 'year_level', 'exam_type', 'scheduled_date', 'is_approved', 'created_by')
    list_filter = ('exam_type', 'department', 'year_level', 'is_approved', 'scheduled_date')
    search_fields = ('title', 'subject', 'created_by__username')
    readonly_fields = ('created_at', 'updated_at', 'approved_at')
    actions = ['approve_exams']
    
    fieldsets = (
        ('Exam Details', {
            'fields': ('title', 'subject', 'department', 'year_level', 'exam_type', 'question_type')
        }),
        ('Schedule', {
            'fields': ('scheduled_date', 'duration_minutes')
        }),
        ('Scoring', {
            'fields': ('total_points', 'passing_score')
        }),
        ('Instructions', {
            'fields': ('instructions',)
        }),
        ('Approval', {
            'fields': ('is_approved', 'approved_by', 'approved_at')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    
    def approve_exams(self, request, queryset):
        from django.utils import timezone
        updated = 0
        for exam in queryset:
            if not exam.is_approved:
                exam.is_approved = True
                exam.approved_by = request.user
                exam.approved_at = timezone.now()
                exam.save()
                updated += 1
        self.message_user(request, f'{updated} exam(s) successfully approved.')
    approve_exams.short_description = 'Approve selected exams'

@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ('student', 'exam', 'score', 'total_points', 'percentage', 'grade', 'remarks', 'submitted_at')
    list_filter = ('grade', 'remarks', 'submitted_at')
    search_fields = ('student__username', 'exam__title')
    readonly_fields = ('percentage', 'grade', 'remarks', 'submitted_at')


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'exam', 'order', 'type', 'points')
    list_filter = ('type', 'exam__department', 'exam__exam_type')
    search_fields = ('exam__title', 'question', 'correct_answer')


class QuestionIssueMessageInline(admin.TabularInline):
    model = QuestionIssueMessage
    extra = 0
    fields = ('sender', 'message', 'created_at')
    readonly_fields = ('sender', 'message', 'created_at')
    can_delete = False


@admin.register(QuestionIssueReport)
class QuestionIssueReportAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'exam',
        'question',
        'student',
        'issue_type',
        'status',
        'created_at',
        'updated_at',
    )
    list_filter = ('status', 'issue_type', 'exam__department', 'created_at')
    search_fields = (
        'exam__title',
        'question__question',
        'student__username',
        'student__first_name',
        'student__last_name',
        'student__school_id',
        'description',
        'reported_answer',
    )
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('exam', 'question', 'student', 'exam_result')
    inlines = [QuestionIssueMessageInline]
    fieldsets = (
        ('Report Details', {
            'fields': ('exam', 'question', 'student', 'exam_result', 'issue_type', 'status')
        }),
        ('Student Submission', {
            'fields': ('description', 'reported_answer')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(QuestionIssueMessage)
class QuestionIssueMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'report', 'sender', 'created_at')
    list_filter = ('sender__role', 'created_at')
    search_fields = ('report__exam__title', 'sender__username', 'message')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('report', 'sender')
