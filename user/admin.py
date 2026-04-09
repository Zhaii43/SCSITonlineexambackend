from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from .models import User, EnrolledStudent, SubjectAssignment

@admin.register(EnrolledStudent)
class EnrolledStudentAdmin(admin.ModelAdmin):
    list_display = ('school_id', 'first_name', 'last_name', 'department', 'year_level', 'email', 'contact_number', 'added_at')
    list_filter = ('department', 'year_level')
    search_fields = ('school_id', 'first_name', 'last_name', 'email')
    ordering = ('department', 'last_name')

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
        """Auto-approve instructors and deans created by admin"""
        if not change:  # New user
            if obj.role in ['instructor', 'dean']:
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


@admin.register(SubjectAssignment)
class SubjectAssignmentAdmin(admin.ModelAdmin):
    list_display = ('subject_name', 'department', 'instructor', 'is_active', 'assigned_by', 'created_at')
    list_filter = ('department', 'is_active')
    search_fields = ('subject_name', 'instructor__username', 'instructor__first_name', 'instructor__last_name')
    ordering = ('department', 'subject_name')
