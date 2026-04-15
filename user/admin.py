from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from .models import User, SubjectAssignment, EnrolledStudent
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'department', 'school_id', 'is_approved', 'is_staff', 'date_joined')
    list_filter = ('role', 'department', 'is_approved', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'school_id')
    actions = ['approve_users', 'reject_users']
    
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'department', 'school_id', 'year_level', 'contact_number', 'study_load')
        }),
        ('Approval', {
            'fields': ('is_approved', 'approved_by', 'approved_at')
        }),
    )
    
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role & Department', {
            'fields': ('role', 'department', 'school_id', 'first_name', 'last_name', 'email')
        }),
    )
    
    def save_model(self, request, obj, form, change):
        """Auto-approve staff roles created by admin"""
        if not change:  # New user
            if obj.role in ['instructor', 'dean', 'edp']:
                obj.is_approved = True
                obj.approved_by = request.user
                obj.approved_at = timezone.now()
        super().save_model(request, obj, form, change)
    
    def approve_users(self, request, queryset):
        """Approve selected users"""
        updated = 0
        for user in queryset:
            if not user.is_approved:
                user.is_approved = True
                user.approved_by = request.user
                user.approved_at = timezone.now()
                user.save()
                updated += 1
        
        self.message_user(request, f'{updated} user(s) successfully approved.')
    approve_users.short_description = 'Approve selected users'
    
    def reject_users(self, request, queryset):
        """Reject/deactivate selected users"""
        updated = queryset.update(is_active=False, is_approved=False)
        self.message_user(request, f'{updated} user(s) successfully rejected.')
    reject_users.short_description = 'Reject selected users'

    def delete_model(self, request, obj):
        if obj.account_source == 'masterlist_import' and obj.school_id:
            EnrolledStudent.objects.filter(school_id=obj.school_id).delete()
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        school_ids = list(
            queryset.filter(account_source='masterlist_import')
            .exclude(school_id__isnull=True)
            .values_list('school_id', flat=True)
        )
        if school_ids:
            EnrolledStudent.objects.filter(school_id__in=school_ids).delete()
        super().delete_queryset(request, queryset)


@admin.register(SubjectAssignment)
class SubjectAssignmentAdmin(admin.ModelAdmin):
    list_display = ('subject_name', 'department', 'instructor', 'is_active', 'assigned_by', 'created_at')
    list_filter = ('department', 'is_active')
    search_fields = ('subject_name', 'instructor__username', 'instructor__first_name', 'instructor__last_name')
    ordering = ('department', 'subject_name')
