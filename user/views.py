from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework import serializers
import secrets
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import models
from django.core.mail import send_mail
from django.http import HttpResponse, FileResponse, StreamingHttpResponse
from django.core.exceptions import ValidationError as DjangoValidationError
from .serializers import RegisterSerializer
from .models import User, PasswordResetToken, PreRegistrationOTP, EnrolledStudent, EmailChangeOTP
from exams.models import Exam
from notifications.models import Notification
from notifications.email_utils import send_student_approval_email, send_password_reset_email, send_bulk_import_email, send_student_rejected_email, send_email_verification_otp, send_pre_registration_otp
from .models import EnrolledStudent
from notifications.push_utils import send_push_notification
from notifications.realtime import send_notification
from .realtime import send_enrollment_records_update, send_student_verification_update
from audit.views import log_activity
from backend.security import require_role, throttle_request, validate_uploaded_file
import re
from urllib.parse import urlparse
import cloudinary
from cloudinary import utils as cloudinary_utils, api as cloudinary_api


def _file_url(request, field):
    """Return the correct public URL for a file field stored in Cloudinary.
    - If the DB value is already a full https URL, return it directly.
    - If it's a relative path, let Cloudinary storage build the URL.
    - If anything fails, return None so the frontend shows the initials fallback.
    """
    if not field or not field.name:
        return None
    name = field.name
    # Already a full URL (e.g. stored incorrectly as full Cloudinary URL)
    if name.startswith('https://') or name.startswith('http://'):
        # Strip any double-URL issue: https://res.cloudinary.com/.../https://res.cloudinary.com/...
        if name.count('https://') > 1:
            name = 'https://' + name.split('https://')[-1]
        return name
    # Relative path — let Cloudinary storage generate the URL
    try:
        return field.url
    except Exception:
        return None


def _cloudinary_public_id_and_format(field):
    if not field or not field.name:
        return None, None, None
    name = field.name
    delivery_type = None
    if name.startswith('http://') or name.startswith('https://'):
        path = urlparse(name).path
        if '/authenticated/' in path:
            delivery_type = 'authenticated'
        elif '/private/' in path:
            delivery_type = 'private'
        else:
            delivery_type = 'upload'
        if '/upload/' in path:
            rest = path.split('/upload/', 1)[1]
        elif '/authenticated/' in path:
            rest = path.split('/authenticated/', 1)[1]
        elif '/private/' in path:
            rest = path.split('/private/', 1)[1]
        else:
            rest = path.lstrip('/')
        rest = re.sub(r'^v\\d+/', '', rest)
        public_id = rest.lstrip('/')
    else:
        public_id = name
    fmt = None
    if public_id and '.' in public_id.split('/')[-1]:
        base, ext = public_id.rsplit('.', 1)
        public_id = base
        fmt = ext
    return public_id, fmt, delivery_type


def _normalize_cloudinary_field(user, field_name):
    field = getattr(user, field_name, None)
    if not field or not getattr(field, 'name', None):
        return
    name = field.name
    if name.startswith('http://') or name.startswith('https://'):
        if 'res.cloudinary.com' not in name:
            return
        public_id, fmt, _ = _cloudinary_public_id_and_format(field)
        if not public_id:
            return
        new_name = public_id + (f'.{fmt}' if fmt else '')
        if new_name != name:
            field.name = new_name
            user.save(update_fields=[field_name])


def _guess_resource_type(public_id, fmt):
    ext = (fmt or public_id.split('.')[-1] if public_id and '.' in public_id else '').lower()
    if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'pdf'):
        return 'image'
    if ext in ('doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'zip', 'rar'):
        return 'raw'
    return 'image'


def _resolve_resource_location(public_id, fmt, hint_type=None):
    resource_hint = _guess_resource_type(public_id, fmt)
    resource_types = [resource_hint, 'raw'] if resource_hint != 'raw' else ['raw', 'image']
    delivery_types = []
    if hint_type in ('authenticated', 'private', 'upload'):
        delivery_types.append(hint_type)
    delivery_types.extend([t for t in ('authenticated', 'private', 'upload') if t not in delivery_types])

    for rtype in resource_types:
        for dtype in delivery_types:
            try:
                res = cloudinary_api.resource(public_id, resource_type=rtype, type=dtype)
                access_mode = res.get('access_mode') or res.get('type')
                if access_mode in ('authenticated', 'private'):
                    return rtype, access_mode
                return rtype, dtype
            except Exception:
                continue
    # Fallback: try upload and honor access_mode if returned
    try:
        res = cloudinary_api.resource(public_id, resource_type=resource_hint, type='upload')
        access_mode = res.get('access_mode')
        if access_mode in ('authenticated', 'private'):
            return resource_hint, access_mode
    except Exception:
        pass
    return resource_hint, (hint_type or 'upload')


class CustomLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = str(request.data.get('password', ''))
        lookup_user = None

        throttle_response = throttle_request(
            request,
            'login',
            limit=5,
            window_seconds=600,
            identifiers=[username],
            message='Too many login attempts. Please wait 10 minutes before trying again.',
        )
        if throttle_response:
            return throttle_response

        if not username or not password:
            return Response({'error': 'Username and password are required.', 'code': 'missing_fields'}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve email to username
        if '@' in username:
            try:
                lookup_user = User.objects.get(email=username)
                username = lookup_user.username
            except User.DoesNotExist:
                return Response({'error': 'No account found with that email. Please check your credentials or register.', 'code': 'account_not_found'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            try:
                lookup_user = User.objects.get(username=username)
            except User.DoesNotExist:
                return Response({'error': 'No account found with that username. Please check your credentials or register.', 'code': 'account_not_found'}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=username, password=password)

        if user is None:
            if (
                lookup_user
                and lookup_user.role == 'student'
                and lookup_user.is_rejected
                and not lookup_user.has_usable_password()
            ):
                return Response(
                    {
                        'error': 'Your account was rejected. Set your password first to continue.',
                        'code': 'password_setup_required',
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            return Response({'error': 'Incorrect password. Please try again.', 'code': 'wrong_password'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.is_active:
            return Response({'error': 'Your account has been deactivated. Please contact support.', 'code': 'account_disabled'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.is_approved:
            if user.role == 'student' and (not user.study_load or user.is_rejected):
                # Bulk-imported student with no study load, or rejected student — allow through so they can fix their info
                pass
            else:
                return Response({'error': 'Your account is pending approval. Please wait for your dean to review your registration.', 'code': 'pending_approval'}, status=status.HTTP_400_BAD_REQUEST)

        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        log_activity(user, 'login', f'{user.username} logged in', request)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)}, status=status.HTTP_200_OK)


# Keep for compatibility but unused
class CustomTokenObtainPairView(TokenObtainPairView):
    pass


class StrictTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        refresh_value = request.data.get('refresh')
        throttle_response = throttle_request(
            request,
            'token_refresh',
            limit=20,
            window_seconds=300,
            identifiers=[refresh_value],
            message='Too many token refresh attempts. Please sign in again.',
        )
        if throttle_response:
            return throttle_response

        try:
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken(refresh_value)
            user = User.objects.get(id=refresh.get('user_id'))
        except Exception:
            return Response({'detail': 'Invalid refresh token'}, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active:
            return Response({'detail': 'User account is disabled'}, status=status.HTTP_401_UNAUTHORIZED)

        return super().post(request, *args, **kwargs)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        import hashlib
        from django.utils import timezone as tz

        # Verify OTP before creating the user
        email = request.data.get('email', '').strip().lower()
        otp_code = str(request.data.get('otp_code', '')).strip()

        if not otp_code:
            return Response(
                {"error": "OTP code is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        otp = PreRegistrationOTP.objects.filter(
            email__iexact=email, code=otp_code, is_verified=True
        ).order_by('-created_at').first()

        if not otp or tz.now() > otp.expires_at:
            if otp:
                otp.delete()
            return Response(
                {"error": "Invalid or expired OTP. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for duplicate email
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {"email": ["Email already exists."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for duplicate username
        username = request.data.get('username')
        if User.objects.filter(username=username).exists():
            return Response(
                {"username": ["Username already exists."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for duplicate school_id
        school_id = request.data.get('school_id')
        if school_id and User.objects.filter(school_id=school_id).exists():
            return Response(
                {"school_id": ["School ID already exists."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for duplicate contact number
        contact_number = request.data.get('contact_number')
        if contact_number and User.objects.filter(contact_number=contact_number).exists():
            return Response(
                {"contact_number": ["Contact number already exists."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate study load file
        study_load = request.FILES.get('study_load')
        if study_load:
            allowed_types = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png']
            if study_load.content_type not in allowed_types:
                return Response(
                    {"error": "Invalid file type. Please upload a PDF or image file (JPG, PNG)."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if study_load.size > 5 * 1024 * 1024:
                return Response(
                    {"error": "File size too large. Maximum file size is 5MB."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            file_hash = hashlib.md5(study_load.read()).hexdigest()
            study_load.seek(0)
            for existing_user in User.objects.filter(study_load__isnull=False):
                if existing_user.study_load:
                    try:
                        with existing_user.study_load.open('rb') as f:
                            if hashlib.md5(f.read()).hexdigest() == file_hash:
                                return Response(
                                    {"error": "This study load document has already been uploaded by another student."},
                                    status=status.HTTP_400_BAD_REQUEST
                                )
                    except:
                        pass

        id_photo = request.FILES.get('id_photo')
        if request.data.get('role') == 'student':
            if not id_photo:
                return Response(
                    {"id_photo": ["ID photo is required."]},
                    status=status.HTTP_400_BAD_REQUEST
                )
            allowed_image_types = ['image/jpeg', 'image/jpg', 'image/png']
            if id_photo.content_type not in allowed_image_types:
                return Response(
                    {"id_photo": ["Invalid file type. Please upload a JPG or PNG image."]},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if id_photo.size > 5 * 1024 * 1024:
                return Response(
                    {"id_photo": ["File size too large. Maximum file size is 5MB."]},
                    status=status.HTTP_400_BAD_REQUEST
                )

        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            otp.delete()
            return Response(
                {
                    "message": "Registration submitted. Your account is pending approval.",
                    "requires_approval": True,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def pre_verify_email(request):
    """Send OTP to an email address for registration verification — no user created yet"""
    from django.utils import timezone as tz
    email = str(request.data.get('email', '')).strip().lower()
    throttle_response = throttle_request(
        request,
        'registration_email_otp',
        limit=5,
        window_seconds=600,
        identifiers=[email],
        message='Too many OTP requests. Please wait 10 minutes before trying again.',
    )
    if throttle_response:
        return throttle_response
    if not email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=email).exists():
        return Response({'error': 'Email already in use by another account.'}, status=status.HTTP_400_BAD_REQUEST)

    # Rate limit: max 3 OTP requests per email per 10 minutes
    ten_minutes_ago = tz.now() - timedelta(minutes=10)
    recent_count = PreRegistrationOTP.objects.filter(
        email__iexact=email, created_at__gte=ten_minutes_ago
    ).count()
    if recent_count >= 3:
        return Response(
            {'error': 'Too many OTP requests. Please wait 10 minutes before trying again.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    # Delete all old OTPs for this email before creating a new one
    PreRegistrationOTP.objects.filter(email__iexact=email).delete()

    otp = PreRegistrationOTP.objects.create(email=email)
    send_pre_registration_otp(email, otp.code)

    return Response({'message': f'OTP sent to {email}'})


@api_view(['POST'])
@permission_classes([AllowAny])
def confirm_pre_verify_email(request):
    """Verify the pre-registration OTP — marks it as verified so register endpoint can use it"""
    email = str(request.data.get('email', '')).strip().lower()
    code = str(request.data.get('code', '')).strip()
    throttle_response = throttle_request(
        request,
        'registration_email_otp_verify',
        limit=8,
        window_seconds=600,
        identifiers=[email],
        message='Too many verification attempts. Please request a new OTP.',
    )
    if throttle_response:
        return throttle_response

    if not email or not code:
        return Response({'error': 'email and code are required'}, status=status.HTTP_400_BAD_REQUEST)

    otp = PreRegistrationOTP.objects.filter(
        email__iexact=email, code=code, is_verified=False
    ).order_by('-created_at').first()

    if not otp or not otp.is_valid():
        return Response({'error': 'Invalid or expired OTP code'}, status=status.HTTP_400_BAD_REQUEST)

    otp.is_verified = True
    otp.expires_at = timezone.now() + timedelta(minutes=30)
    otp.save()

    return Response({'message': 'OTP verified. Proceed to complete registration.', 'email': email})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_user_profile(request):
    """Get authenticated user profile"""
    user = request.user
    _normalize_cloudinary_field(user, 'study_load')
    return Response({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
        'department': user.department,
        'school_id': user.school_id,
        'year_level': user.year_level,
        'contact_number': user.contact_number,
        'profile_picture': _file_url(request, user.profile_picture),
        'id_photo': _file_url(request, user.id_photo),
        'id_verified': user.id_verified,
        'id_verified_at': user.id_verified_at.isoformat() if user.id_verified_at else None,
        'study_load': _file_url(request, user.study_load),
        'is_approved': user.is_approved,
        'is_active': user.is_active,
        'is_rejected': user.is_rejected,
        'rejection_reason': user.rejection_reason,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_department_users(request):
    """Get students and instructors from dean's department"""
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    students = User.objects.filter(department=user.department, role='student', is_approved=True)
    
    # Get all instructors: from dean's department and GENERAL department
    instructors = User.objects.filter(
        role='instructor', 
        is_approved=True
    ).filter(
        models.Q(department=user.department) | models.Q(department='GENERAL')
    ).distinct()
    
    students_list = [{
        'id': s.id,
        'username': s.username,
        'email': s.email,
        'first_name': s.first_name,
        'last_name': s.last_name,
        'school_id': s.school_id,
        'year_level': s.year_level,
        'contact_number': s.contact_number,
        'is_transferee': s.is_transferee,
        'is_irregular': s.is_irregular,
        'extra_approved': s.extra_approved,
        'is_approved': s.is_approved,
    } for s in students]
    
    instructors_list = [{
        'id': i.id,
        'username': i.username,
        'email': i.email,
        'first_name': i.first_name,
        'last_name': i.last_name,
        'school_id': i.school_id,
        'contact_number': i.contact_number,
        'department': i.department,
        'subject_type': 'General' if i.department == 'GENERAL' else i.department,
    } for i in instructors]
    
    return Response({
        'students': students_list,
        'instructors': instructors_list
    })



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_pending_students(request):
    """Get pending student registrations for dean's department"""
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    pending_students = User.objects.filter(
        department=user.department,
        role='student',
        is_approved=False,
        is_rejected=False,
        is_active=True,
        is_staff=False,
        is_superuser=False
    ).order_by('-date_joined')

    for s in pending_students:
        _normalize_cloudinary_field(s, 'study_load')
    
    students_list = [{
        'id': s.id,
        'username': s.username,
        'email': s.email,
        'first_name': s.first_name,
        'last_name': s.last_name,
        'school_id': s.school_id,
        'year_level': s.year_level,
        'contact_number': s.contact_number,
        'date_joined': s.date_joined.isoformat(),
        'profile_picture': _file_url(request, s.profile_picture),
        'study_load': _file_url(request, s.study_load),
        'id_photo': _file_url(request, s.id_photo),
        'id_verified': s.id_verified,
        'is_transferee': s.is_transferee,
        'is_irregular': s.is_irregular,
        'declaration_verified': s.declaration_verified,
    } for s in pending_students]
    
    return Response(students_list)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_student(request, student_id):
    """Approve a student registration"""
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can approve students'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        from django.utils import timezone
        student = User.objects.get(id=student_id, department=user.department, role='student')

        if not student.id_photo:
            return Response({'error': 'Student must upload an ID photo before approval.'}, status=status.HTTP_400_BAD_REQUEST)
        if not student.id_verified:
            return Response({'error': 'Student ID photo must be verified before approval.'}, status=status.HTTP_400_BAD_REQUEST)
        if (student.is_transferee or student.is_irregular) and not student.declaration_verified:
            return Response({'error': 'Student declaration must be verified before approval.'}, status=status.HTTP_400_BAD_REQUEST)

        student.is_approved = True
        student.approved_by = user
        student.approved_at = timezone.now()
        student.save(update_fields=['is_approved', 'approved_by', 'approved_at'])

        Notification.objects.create(
            user=student,
            type='account_approved',
            title='Account Approved',
            message='Your account has been approved. You can now log in and access the system.',
            link='/login'
        )
        
        # Send approval email
        send_student_approval_email(student)

        # Send push notification
        send_push_notification(
            student.expo_push_token,
            '✅ Account Approved',
            'Your account has been approved. You can now access exams.',
        )
        
        log_activity(user, 'student_approved', f'Approved student {student.username}', request, {'student_id': student.id})
        send_student_verification_update(user.department, 'approved', student.id)

        return Response({'message': 'Student approved successfully'})
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_id_photo_verification(request, student_id):
    """Allow deans to verify or unverify a student's uploaded ID photo during student verification."""
    user = request.user

    if user.role != 'dean':
        return Response({'error': 'Only deans can verify ID photos'}, status=status.HTTP_403_FORBIDDEN)

    try:
        student = User.objects.get(id=student_id, department=user.department, role='student')
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    if not student.id_photo:
        return Response({'error': 'Student has not uploaded an ID photo'}, status=status.HTTP_400_BAD_REQUEST)

    requested = request.data.get('id_verified', True)
    verified = bool(requested)

    if verified:
        student.id_verified = True
        student.id_verified_by = user
        student.id_verified_at = timezone.now()
    else:
        student.id_verified = False
        student.id_verified_by = None
        student.id_verified_at = None

    student.save(update_fields=['id_verified', 'id_verified_by', 'id_verified_at'])

    log_activity(
        user,
        'student_id_photo_verification_updated',
        f'Updated ID photo verification for {student.username} to {verified}',
        request,
        {'student_id': student.id, 'id_verified': verified},
    )
    send_student_verification_update(user.department, 'id_photo_verification_updated', student.id, {
        'id_verified': student.id_verified,
    })

    return Response({
        'message': 'ID photo verification updated',
        'id_verified': student.id_verified,
        'id_verified_at': student.id_verified_at.isoformat() if student.id_verified_at else None,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_approve_students(request):
    """Bulk approve multiple students"""
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can approve students'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        from django.utils import timezone
        student_ids = request.data.get('student_ids', [])
        
        if not student_ids:
            return Response({'error': 'No students selected'}, status=status.HTTP_400_BAD_REQUEST)
        
        students = User.objects.filter(
            id__in=student_ids, 
            department=user.department, 
            role='student'
        )

        # Block transferee/irregular students without declaration verification
        unverified_decl = students.filter(
            models.Q(is_transferee=True) | models.Q(is_irregular=True),
            declaration_verified=False
        )
        if unverified_decl.exists():
            names = ', '.join([s.get_full_name() or s.username for s in unverified_decl])
            return Response(
                {'error': f'Cannot approve: declaration not verified for {names}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        missing_id_photo = students.filter(models.Q(id_photo='') | models.Q(id_photo__isnull=True))
        if missing_id_photo.exists():
            names = ', '.join([s.get_full_name() or s.username for s in missing_id_photo])
            return Response(
                {'error': f'Cannot approve: the following students are missing ID photo: {names}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        unverified_ids = students.filter(id_verified=False)
        if unverified_ids.exists():
            names = ', '.join([s.get_full_name() or s.username for s in unverified_ids])
            return Response(
                {'error': f'Cannot approve: ID photo not verified for {names}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Block any without study load
        incomplete = students.filter(models.Q(study_load='') | models.Q(study_load__isnull=True))
        if incomplete.exists():
            names = ', '.join([s.get_full_name() or s.username for s in incomplete])
            return Response(
                {'error': f'Cannot approve: the following students are missing study load: {names}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        def norm(value):
            return str(value or '').strip().lower().replace(' ', '')

        def digits_only(value):
            return ''.join([c for c in str(value or '') if c.isdigit()])

        invalid = []
        valid_students = []
        for student in students:
            if not student.school_id:
                invalid.append(student)
                continue
            try:
                record = EnrolledStudent.objects.get(school_id=student.school_id)
            except EnrolledStudent.DoesNotExist:
                invalid.append(student)
                continue

            name_match = norm(student.first_name + student.last_name) == norm(record.first_name + record.last_name)
            id_match = norm(student.school_id) == norm(record.school_id)
            year_match = digits_only(student.year_level) == digits_only(record.year_level)

            if name_match and id_match and year_match:
                valid_students.append(student)
            else:
                invalid.append(student)

        if invalid:
            names = ', '.join([s.get_full_name() or s.username for s in invalid])
            return Response(
                {'error': f'Cannot approve: enrollment record mismatch or missing for {names}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        student_list = list(valid_students)
        
        count = User.objects.filter(id__in=[s.id for s in valid_students]).update(
            is_approved=True,
            approved_by=user,
            approved_at=timezone.now(),
        )

        if count > 0:
            notifications = []
            for student in student_list:
                notifications.append(
                    Notification(
                        user=student,
                        type='account_approved',
                        title='Account Approved',
                        message='Your account has been approved. You can now log in and access the system.',
                        link='/login'
                    )
                )
                # Send approval email to each student
                send_student_approval_email(student)
            
            created = Notification.objects.bulk_create(notifications)
            for n in created:
                send_notification(n)
            for student in student_list:
                send_student_verification_update(user.department, 'approved', student.id)
          
        return Response({
            'message': f'{count} student(s) approved successfully',
            'count': count
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_student(request, student_id):
    """Reject a student registration (soft reject — keeps account so student can fix and resubmit)"""
    user = request.user

    if user.role != 'dean':
        return Response({'error': 'Only deans can reject students'},
                       status=status.HTTP_403_FORBIDDEN)

    rejection_reason = request.data.get('rejection_reason', '').strip()
    if not rejection_reason:
        return Response({'error': 'Rejection reason is required'},
                       status=status.HTTP_400_BAD_REQUEST)

    try:
        student = User.objects.get(id=student_id, department=user.department, role='student')
        student.is_rejected = True
        student.rejection_reason = rejection_reason
        student.is_approved = False
        student.save(update_fields=['is_rejected', 'rejection_reason', 'is_approved'])

        send_student_rejected_email(student, rejection_reason)
        log_activity(user, 'student_rejected', f'Rejected student {student.username}: {rejection_reason}', request, {'student_id': student_id})
        send_student_verification_update(user.department, 'rejected', student.id)

        return Response({'message': 'Student registration rejected'})
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_extra_approval(request, student_id):
    """Toggle extra approval for transferee/irregular students"""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can approve extra access'}, status=status.HTTP_403_FORBIDDEN)
    try:
        student = User.objects.get(id=student_id, department=user.department, role='student')
        if not student.is_approved:
            return Response({'error': 'Student must be approved first'}, status=status.HTTP_400_BAD_REQUEST)
        if not (student.is_transferee or student.is_irregular):
            return Response({'error': 'Student is not marked as transferee or irregular'}, status=status.HTTP_400_BAD_REQUEST)
        requested = request.data.get('extra_approved', True)
        extra = bool(requested)
        from django.utils import timezone
        student.extra_approved = extra
        if extra:
            student.extra_approved_by = user
            student.extra_approved_at = timezone.now()
        else:
            student.extra_approved_by = None
            student.extra_approved_at = None
        student.save(update_fields=['extra_approved', 'extra_approved_by', 'extra_approved_at'])
        return Response({
            'message': 'Extra approval updated',
            'extra_approved': student.extra_approved,
        })
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_declaration_verification(request, student_id):
    """Toggle declaration verification for transferee/irregular students (pre-approval)"""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can verify declarations'}, status=status.HTTP_403_FORBIDDEN)
    try:
        student = User.objects.get(id=student_id, department=user.department, role='student', is_approved=False)
        if not (student.is_transferee or student.is_irregular):
            return Response({'error': 'Student did not declare transferee or irregular status'}, status=status.HTTP_400_BAD_REQUEST)
        requested = request.data.get('declaration_verified', True)
        verified = bool(requested)
        from django.utils import timezone
        student.declaration_verified = verified
        if verified:
            student.declaration_verified_by = user
            student.declaration_verified_at = timezone.now()
        else:
            student.declaration_verified_by = None
            student.declaration_verified_at = None
        student.save(update_fields=['declaration_verified', 'declaration_verified_by', 'declaration_verified_at'])
        send_student_verification_update(user.department, 'declaration_verification_updated', student.id, {
            'declaration_verified': student.declaration_verified,
        })
        return Response({
            'message': 'Declaration verification updated',
            'declaration_verified': student.declaration_verified,
        })
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_study_load_signed_url(request, student_id):
    """Stream the study load file through the backend — avoids Cloudinary 401."""
    user = request.user
    if user.role == 'dean':
        student = User.objects.filter(id=student_id, department=user.department, role='student').first()
    elif int(student_id) == user.id:
        student = User.objects.filter(id=student_id).first()
    else:
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    if not student:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    if not student.study_load:
        return Response({'error': 'No study load uploaded'}, status=status.HTTP_404_NOT_FOUND)

    public_id, fmt, hint_type = _cloudinary_public_id_and_format(student.study_load)
    if not public_id:
        return Response({'error': 'Invalid file reference'}, status=status.HTTP_400_BAD_REQUEST)

    import urllib.request as urllib_req

    # Try all combinations until one works
    for rtype in ['image', 'raw']:
        for dtype in ['upload', 'authenticated', 'private']:
            try:
                url, _ = cloudinary_utils.cloudinary_url(
                    public_id,
                    resource_type=rtype,
                    type=dtype,
                    format=fmt,
                    sign_url=True,
                    secure=True,
                )
                remote = urllib_req.urlopen(url, timeout=15)
                content_type = remote.headers.get('Content-Type', 'application/octet-stream')
                filename = public_id.split('/')[-1]
                if fmt:
                    filename += f'.{fmt}'
                response = StreamingHttpResponse(remote, content_type=content_type)
                response['Content-Disposition'] = f'inline; filename="{filename}"'
                response['Cache-Control'] = 'private, no-store'
                response['X-Content-Type-Options'] = 'nosniff'
                return response
            except Exception:
                continue

    return Response({'error': 'Unable to open study load file'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def proxy_study_load(request, student_id):
    """Stream the study load file through Django so the browser never hits Cloudinary directly."""
    user = request.user
    if not user.is_authenticated:
        token = request.query_params.get('token')
        if not token:
            return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            access = AccessToken(token)
            user_id = access.get('user_id')
            user = User.objects.get(id=user_id)
        except Exception:
            return Response({'error': 'Invalid token'}, status=status.HTTP_401_UNAUTHORIZED)

    if user.role == 'dean':
        student = User.objects.filter(id=student_id, department=user.department, role='student').first()
    elif int(student_id) == user.id:
        student = User.objects.filter(id=student_id).first()
    else:
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    if not student:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    if not student.study_load:
        return Response({'error': 'No study load uploaded'}, status=status.HTTP_404_NOT_FOUND)

    public_id, fmt, hint_type = _cloudinary_public_id_and_format(student.study_load)
    if not public_id:
        return Response({'error': 'Invalid file reference'}, status=status.HTTP_400_BAD_REQUEST)

    filename = public_id.split('/')[-1]
    if fmt:
        filename += f'.{fmt}'

    import urllib.request as urllib_req
    import urllib.error as urllib_err

    candidate_urls = []
    # Direct URL if storage provides it
    try:
        direct = _file_url(request, student.study_load)
        if direct:
            candidate_urls.append(direct)
    except Exception:
        pass

    for rtype in ['image', 'raw']:
        for dtype in ['upload', 'authenticated', 'private']:
            try:
                url, _ = cloudinary_utils.cloudinary_url(
                    public_id,
                    resource_type=rtype,
                    type=dtype,
                    format=fmt,
                    sign_url=True,
                    secure=True,
                )
                candidate_urls.append(url)
            except Exception:
                continue
            try:
                if hasattr(cloudinary_utils, 'private_download_url'):
                    dl_url = cloudinary_utils.private_download_url(
                        public_id,
                        fmt,
                        resource_type=rtype,
                        type=dtype,
                        attachment=False,
                    )
                    candidate_urls.append(dl_url)
            except Exception:
                pass

    for url in candidate_urls:
        try:
            remote = urllib_req.urlopen(url, timeout=20)
            content_type = remote.headers.get('Content-Type', 'application/octet-stream')
            resp = StreamingHttpResponse(remote, content_type=content_type)
            resp['Content-Disposition'] = f'inline; filename="{filename}"'
            resp['Cache-Control'] = 'private, no-store'
            resp['X-Content-Type-Options'] = 'nosniff'
            return resp
        except urllib_err.HTTPError:
            continue
        except Exception:
            continue

    return Response({'error': 'Unable to open study load file'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resubmit_registration(request):
    """Allow a rejected student to update their info and resubmit for approval."""
    user = request.user

    if user.role != 'student':
        return Response({'error': 'Only students can resubmit'}, status=status.HTTP_403_FORBIDDEN)

    if not user.is_rejected:
        return Response({'error': 'Your account is not in a rejected state'}, status=status.HTTP_400_BAD_REQUEST)

    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    school_id = request.data.get('school_id', '').strip()
    year_level = request.data.get('year_level', '').strip()
    contact_number = request.data.get('contact_number', '').strip()

    if not all([first_name, last_name, school_id, year_level]):
        return Response({'error': 'first_name, last_name, school_id, and year_level are required'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(school_id=school_id).exclude(pk=user.pk).exists():
        return Response({'error': 'School ID is already in use by another account'}, status=status.HTTP_400_BAD_REQUEST)

    user.first_name = first_name
    user.last_name = last_name
    user.school_id = school_id
    user.year_level = year_level
    if contact_number:
        user.contact_number = contact_number
    user.is_rejected = False
    user.rejection_reason = None
    user.is_approved = False
    user.save(update_fields=['first_name', 'last_name', 'school_id', 'year_level', 'contact_number', 'is_rejected', 'rejection_reason', 'is_approved'])

    log_activity(user, 'registration_resubmitted', f'{user.username} resubmitted registration', request)
    send_student_verification_update(user.department, 'registration_resubmitted', user.id)
    return Response({'message': 'Registration resubmitted successfully. Please wait for dean approval.'})



@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """Update user profile"""
    user = request.user

    try:
        new_username = request.data.get('username', '').strip()
        if new_username and new_username != user.username:
            if User.objects.filter(username=new_username).exclude(pk=user.pk).exists():
                return Response({'error': 'Username is already in use by another account.'}, status=status.HTTP_400_BAD_REQUEST)
            user.username = new_username

        user.first_name = request.data.get('first_name', user.first_name)
        user.last_name = request.data.get('last_name', user.last_name)
        user.contact_number = request.data.get('contact_number', user.contact_number)

        new_email = request.data.get('email', '').strip()
        if new_email and new_email != user.email:
            if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                return Response({'error': 'Email is already in use by another account.'}, status=status.HTTP_400_BAD_REQUEST)
            # Email updates require verification; use email change endpoints.
            return Response({'error': 'Email change requires verification. Please use the email change flow.'}, status=status.HTTP_400_BAD_REQUEST)

        if 'profile_picture' in request.FILES:
            profile_error = validate_uploaded_file(
                request.FILES['profile_picture'],
                allowed_extensions={'.jpg', '.jpeg', '.png', '.webp'},
                allowed_content_types={'image/jpeg', 'image/png', 'image/webp'},
                max_size_bytes=5 * 1024 * 1024,
            )
            if profile_error:
                return Response({'error': profile_error}, status=status.HTTP_400_BAD_REQUEST)
            user.profile_picture = request.FILES['profile_picture']

        user.save()

        log_activity(user, 'profile_updated', f'{user.username} updated profile', request)

        return Response({
            'message': 'Profile updated successfully',
            'user': {
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'email': user.email,
                'contact_number': user.contact_number,
                'profile_picture': _file_url(request, user.profile_picture),
            }
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_email_change(request):
    """Send OTP to new email for profile email change."""
    user = request.user
    new_email = str(request.data.get('email', '')).strip().lower()
    throttle_response = throttle_request(
        request,
        'email_change_request',
        limit=4,
        window_seconds=600,
        identifiers=[user.id, new_email],
        message='Too many email change OTP requests. Please wait 10 minutes before trying again.',
    )
    if throttle_response:
        return throttle_response

    if not new_email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

    if user.email and new_email == user.email.lower():
        return Response({'error': 'New email must be different from your current email.'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
        return Response({'error': 'Email already in use by another account.'}, status=status.HTTP_400_BAD_REQUEST)

    EmailChangeOTP.objects.filter(user=user, is_used=False).delete()
    otp = EmailChangeOTP.objects.create(user=user, new_email=new_email)
    send_pre_registration_otp(new_email, otp.code)

    log_activity(user, 'email_change_requested', f'{user.username} requested email change', request, {
        'new_email': new_email
    })

    return Response({'message': f'OTP sent to {new_email}', 'email': new_email})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_email_change_otp(request):
    """Resend OTP for a pending email change."""
    user = request.user
    new_email = str(request.data.get('email', '')).strip().lower()
    throttle_response = throttle_request(
        request,
        'email_change_resend',
        limit=4,
        window_seconds=600,
        identifiers=[user.id, new_email],
        message='Too many OTP resend attempts. Please wait 10 minutes before trying again.',
    )
    if throttle_response:
        return throttle_response

    if not new_email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
        return Response({'error': 'Email already in use by another account.'}, status=status.HTTP_400_BAD_REQUEST)

    EmailChangeOTP.objects.filter(user=user, new_email__iexact=new_email, is_used=False).delete()
    otp = EmailChangeOTP.objects.create(user=user, new_email=new_email)
    send_pre_registration_otp(new_email, otp.code)

    return Response({'message': f'OTP resent to {new_email}', 'email': new_email})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_email_change(request):
    """Verify OTP and apply the email change."""
    user = request.user
    new_email = str(request.data.get('email', '')).strip().lower()
    code = str(request.data.get('code', '')).strip()
    throttle_response = throttle_request(
        request,
        'email_change_verify',
        limit=8,
        window_seconds=600,
        identifiers=[user.id, new_email],
        message='Too many OTP verification attempts. Please request a new code.',
    )
    if throttle_response:
        return throttle_response

    if not new_email or not code:
        return Response({'error': 'Email and code are required'}, status=status.HTTP_400_BAD_REQUEST)

    otp = EmailChangeOTP.objects.filter(
        user=user, new_email__iexact=new_email, is_used=False
    ).order_by('-created_at').first()

    if not otp or not otp.is_valid() or otp.code != code:
        return Response({'error': 'Invalid or expired OTP code'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
        return Response({'error': 'Email already in use by another account.'}, status=status.HTTP_400_BAD_REQUEST)

    user.email = new_email
    user.save(update_fields=['email'])
    otp.is_used = True
    otp.save(update_fields=['is_used'])

    log_activity(user, 'email_changed', f'{user.username} changed email', request, {
        'new_email': new_email
    })

    return Response({'message': 'Email updated successfully', 'email': new_email})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_department_stats(request):
    """Get department-level stats for dean dashboard"""
    user = request.user

    if user.role != 'dean':
        return Response({'error': 'Only deans can access department stats'}, status=status.HTTP_403_FORBIDDEN)

    department = user.department
    students_count = User.objects.filter(role='student', department=department).count()
    instructors_count = User.objects.filter(role='instructor', department=department).count()
    exams_count = Exam.objects.filter(department=department).count()

    return Response({
        'students': students_count,
        'instructors': instructors_count,
        'exams': exams_count,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """Change user password"""
    user = request.user
    
    old_password = request.data.get('old_password')
    new_password = request.data.get('new_password')
    
    if not old_password or not new_password:
        return Response({'error': 'Both old and new passwords are required'}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    if not user.check_password(old_password):
        return Response({'error': 'Current password is incorrect'}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        return Response({'error': ' '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    
    user.set_password(new_password)
    user.save()
    
    log_activity(user, 'password_changed', f'{user.username} changed password', request)
    
    return Response({'message': 'Password changed successfully'})


@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    """Step 1 — send a 6-digit OTP code to the user's email"""
    from django.utils import timezone as tz
    email = request.data.get('email', '').strip()
    throttle_response = throttle_request(
        request,
        'password_reset_request',
        limit=5,
        window_seconds=600,
        identifiers=[email],
        message='Too many password reset requests. Please wait 10 minutes before trying again.',
    )
    if throttle_response:
        return throttle_response

    if not email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'error': 'No account found with that email address.'}, status=status.HTTP_400_BAD_REQUEST)

    # Rate limit: max 3 reset requests per user per 10 minutes
    ten_minutes_ago = tz.now() - timedelta(minutes=10)
    recent_count = PasswordResetToken.objects.filter(
        user=user, created_at__gte=ten_minutes_ago
    ).count()
    if recent_count >= 3:
        return Response(
            {'error': 'Too many reset requests. Please wait 10 minutes before trying again.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )

    # Delete old unused tokens and create a fresh 6-digit code
    PasswordResetToken.objects.filter(user=user, is_used=False).delete()
    reset_token = PasswordResetToken.objects.create(user=user)

    send_password_reset_email(user, reset_token.token)
    log_activity(user, 'password_reset_requested', f'{user.username} requested password reset', request)

    return Response({'message': f'A 6-digit verification code has been sent to {email}'})


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_reset_code(request):
    """Step 2 — verify the 6-digit code, return the token for step 3"""
    email = request.data.get('email', '').strip()
    code = request.data.get('code', '').strip()
    throttle_response = throttle_request(
        request,
        'password_reset_verify',
        limit=8,
        window_seconds=600,
        identifiers=[email],
        message='Too many verification attempts. Please request a new reset code.',
    )
    if throttle_response:
        return throttle_response

    if not email or not code:
        return Response({'error': 'Email and code are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'error': 'Invalid code'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        reset_token = PasswordResetToken.objects.get(user=user, token=code, is_used=False)
    except PasswordResetToken.DoesNotExist:
        return Response({'error': 'Invalid or incorrect verification code.'}, status=status.HTTP_400_BAD_REQUEST)

    if not reset_token.is_valid():
        return Response({'error': 'This code has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)

    return Response({'message': 'Code verified', 'token': reset_token.token})


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    """Reset password using token"""
    token = request.data.get('token')
    new_password = request.data.get('new_password')
    throttle_response = throttle_request(
        request,
        'password_reset_apply',
        limit=6,
        window_seconds=600,
        identifiers=[token],
        message='Too many password reset attempts. Please request a new reset code.',
    )
    if throttle_response:
        return throttle_response
    
    if not token or not new_password:
        return Response({'error': 'Token and new password are required'}, 
                       status=status.HTTP_400_BAD_REQUEST)
    
    try:
        reset_token = PasswordResetToken.objects.get(token=token)
        
        if not reset_token.is_valid():
            return Response({'error': 'Token is invalid or expired'}, 
                           status=status.HTTP_400_BAD_REQUEST)
        
        user = reset_token.user
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({'error': ' '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(new_password)
        user.save()
        
        reset_token.is_used = True
        reset_token.save()
        
        log_activity(user, 'password_reset', f'{user.username} reset password', request)
        
        return Response({'message': 'Password reset successfully'})
    except PasswordResetToken.DoesNotExist:
        return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def validate_reset_token(request):
    """Validate if reset token is valid"""
    token = request.data.get('token')
    
    if not token:
        return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        reset_token = PasswordResetToken.objects.get(token=token)
        
        if reset_token.is_valid():
            return Response({
                'valid': True,
                'email': reset_token.user.email
            })
        else:
            return Response({'valid': False, 'error': 'Token expired or already used'})
    except PasswordResetToken.DoesNotExist:
        return Response({'valid': False, 'error': 'Invalid token'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_documents(request):
    """Allow students to upload their ID photo and/or study load"""
    user = request.user
    updated = []

    role_response = require_role(user, 'student', message='Only students can upload verification documents')
    if role_response:
        return role_response

    if 'id_photo' in request.FILES:
        id_photo_error = validate_uploaded_file(
            request.FILES['id_photo'],
            allowed_extensions={'.jpg', '.jpeg', '.png', '.webp'},
            allowed_content_types={'image/jpeg', 'image/png', 'image/webp'},
            max_size_bytes=5 * 1024 * 1024,
        )
        if id_photo_error:
            return Response({'error': id_photo_error}, status=status.HTTP_400_BAD_REQUEST)
        user.id_photo = request.FILES['id_photo']
        user.id_verified = False
        updated.append('id_photo')

    if 'study_load' in request.FILES:
        study_load_error = validate_uploaded_file(
            request.FILES['study_load'],
            allowed_extensions={'.pdf', '.jpg', '.jpeg', '.png'},
            allowed_content_types={'application/pdf', 'image/jpeg', 'image/png'},
            max_size_bytes=10 * 1024 * 1024,
        )
        if study_load_error:
            return Response({'error': study_load_error}, status=status.HTTP_400_BAD_REQUEST)
        user.study_load = request.FILES['study_load']
        updated.append('study_load')

    if not updated:
        return Response({'error': 'No files provided'}, status=status.HTTP_400_BAD_REQUEST)

    user.save()

    log_activity(user, 'documents_uploaded', f'{user.username} uploaded: {", ".join(updated)}', request)
    send_student_verification_update(user.department, 'documents_uploaded', user.id, {
        'updated_fields': updated,
    })

    return Response({
        'message': 'Documents uploaded successfully',
        'id_photo': _file_url(request, user.id_photo),
        'study_load': _file_url(request, user.study_load),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_import_students(request):
    """Bulk import students from a plain CSV file"""
    user = request.user

    role_response = require_role(user, 'dean', message='Only deans can import students')
    if role_response:
        return role_response

    if 'file' not in request.FILES:
        return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

    csv_file = request.FILES['file']
    csv_error = validate_uploaded_file(
        csv_file,
        allowed_extensions={'.csv'},
        allowed_content_types={'text/csv', 'application/vnd.ms-excel', 'application/csv'},
        max_size_bytes=2 * 1024 * 1024,
    )
    if csv_error:
        return Response({'error': csv_error}, status=status.HTTP_400_BAD_REQUEST)
    filename = csv_file.name.lower()

    if not filename.endswith('.csv'):
        return Response({'error': 'File must be a CSV file'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        import csv
        import io
        from django.utils import timezone

        decoded_file = csv_file.read().decode('utf-8-sig')
        io_string = io.StringIO(decoded_file)
        reader = csv.DictReader(io_string)
        reader.fieldnames = [f.strip() for f in (reader.fieldnames or [])]

        success_count = 0
        error_count = 0
        errors = []

        for row_num, row in enumerate(reader, start=2):
            try:
                row = {k: (v.strip() if v else v) for k, v in row.items()}
                required_fields = ['username', 'email', 'first_name', 'last_name', 'school_id', 'year_level', 'contact_number']
                missing_fields = [f for f in required_fields if not row.get(f)]

                if missing_fields:
                    errors.append({'row': row_num, 'error': f'Missing required fields: {", ".join(missing_fields)}', 'data': row})
                    error_count += 1
                    continue

                if User.objects.filter(username=row['username']).exists():
                    errors.append({'row': row_num, 'error': f'Username "{row["username"]}" already exists', 'data': row})
                    error_count += 1
                    continue

                if User.objects.filter(email=row['email']).exists():
                    errors.append({'row': row_num, 'error': f'Email "{row["email"]}" already exists', 'data': row})
                    error_count += 1
                    continue

                if User.objects.filter(school_id=row['school_id']).exists():
                    errors.append({'row': row_num, 'error': f'School ID "{row["school_id"]}" already exists', 'data': row})
                    error_count += 1
                    continue

                if User.objects.filter(contact_number=row['contact_number']).exists():
                    errors.append({'row': row_num, 'error': f'Contact number "{row["contact_number"]}" already exists', 'data': row})
                    error_count += 1
                    continue

                year_level_map = {'1st': '1', '2nd': '2', '3rd': '3', '4th': '4', '1': '1', '2': '2', '3': '3', '4': '4'}
                if row['year_level'] not in year_level_map:
                    errors.append({'row': row_num, 'error': f'Invalid year level "{row["year_level"]}". Must be: 1st, 2nd, 3rd, 4th', 'data': row})
                    error_count += 1
                    continue

                student = User(
                    username=row['username'],
                    email=row['email'],
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    school_id=row['school_id'],
                    year_level=year_level_map[row['year_level']],
                    contact_number=row['contact_number'],
                    department=user.department,
                    role='student',
                    is_approved=False,
                )
                student.set_unusable_password()
                student.save()

                # Create a 7-day token for setting password
                from django.utils import timezone as tz
                reset_token = PasswordResetToken(
                    user=student,
                    expires_at=tz.now() + timedelta(days=7),
                )
                reset_token.save()

                Notification.objects.create(
                    user=student,
                    type='account_approved',
                    title='Account Created — Action Required',
                    message='Your account has been created. Please check your email to set your password.',
                    link='/login'
                )
                send_bulk_import_email(student, reset_token.token)
                success_count += 1

            except Exception as e:
                errors.append({'row': row_num, 'error': str(e), 'data': row})
                error_count += 1

        log_activity(user, 'bulk_import_students', f'Imported {success_count} students, {error_count} errors', request, {
            'success_count': success_count, 'error_count': error_count
        })

        return Response({
            'message': f'Import completed: {success_count} students imported successfully, {error_count} errors',
            'success_count': success_count,
            'error_count': error_count,
            'errors': errors
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_registration_email(request):
    """Verify email OTP after registration"""
    user_id = request.data.get('user_id')
    code = str(request.data.get('code', '')).strip()

    if not user_id or not code:
        return Response({'error': 'user_id and code are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(id=int(user_id), is_approved=False)
    except (User.DoesNotExist, ValueError):
        return Response({'error': 'Invalid request'}, status=status.HTTP_400_BAD_REQUEST)

    otp = PreRegistrationOTP.objects.filter(
        email__iexact=user.email, code=code, is_verified=False
    ).order_by('-created_at').first()
    if not otp or not otp.is_valid():
        return Response({'error': 'Invalid or expired OTP code'}, status=status.HTTP_400_BAD_REQUEST)

    otp.is_verified = True
    otp.save()

    return Response({'message': 'Email verified. Your account is pending approval.', 'requires_approval': True})


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_registration_email_otp(request):
    """Resend email verification OTP for registration"""
    user_id = request.data.get('user_id')
    if not user_id:
        return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(id=int(user_id), is_approved=False)
    except (User.DoesNotExist, ValueError):
        return Response({'error': 'Invalid request'}, status=status.HTTP_400_BAD_REQUEST)

    PreRegistrationOTP.objects.filter(email__iexact=user.email, is_verified=False).delete()
    otp = PreRegistrationOTP.objects.create(email=user.email)
    send_email_verification_otp(user, otp.code)

    return Response({'message': f'OTP resent to {user.email}'})


@api_view(['POST'])
@permission_classes([AllowAny])
def update_registration_email(request):
    """Allow a pending (unverified) user to update their email before verification"""
    user_id = request.data.get('user_id')
    new_email = str(request.data.get('email', '')).strip()

    if not user_id or not new_email:
        return Response({'error': 'user_id and email are required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = User.objects.get(id=int(user_id), is_approved=False)
    except (User.DoesNotExist, ValueError):
        return Response({'error': 'Invalid request'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
        return Response({'error': 'Email already in use by another account.'}, status=status.HTTP_400_BAD_REQUEST)

    user.email = new_email
    user.save(update_fields=['email'])

    PreRegistrationOTP.objects.filter(email__iexact=user.email, is_verified=False).delete()
    otp = PreRegistrationOTP.objects.create(email=user.email)
    send_email_verification_otp(user, otp.code)

    return Response({'message': f'Email updated and OTP sent to {new_email}', 'email': new_email})



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_push_token(request):
    """Save Expo push token for the authenticated user"""
    token = request.data.get('expo_push_token')
    if not token:
        return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
    request.user.expo_push_token = token
    request.user.save(update_fields=['expo_push_token'])
    return Response({'message': 'Push token saved'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_student_template(request):
    """Download CSV template for bulk student import"""
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can download template'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    import csv
    from django.http import HttpResponse
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="student_import_template.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['username', 'email', 'first_name', 'last_name', 'school_id', 'year_level', 'contact_number'])
    writer.writerow(['jdoe2024', 'jdoe@example.com', 'John', 'Doe', '2024-001', '1st', '09123456789'])
    writer.writerow(['msmith2024', 'msmith@example.com', 'Mary', 'Smith', '2024-002', '2nd', '09234567890'])
    
    return response


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_student_school_id(request, student_id):
    """Allow a dean to correct a pending student's school_id before approval."""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can perform this action'}, status=status.HTTP_403_FORBIDDEN)

    try:
        student = User.objects.get(id=student_id, department=user.department, role='student', is_approved=False)
    except User.DoesNotExist:
        return Response({'error': 'Pending student not found'}, status=status.HTTP_404_NOT_FOUND)

    new_school_id = request.data.get('school_id', '').strip()
    if not new_school_id:
        return Response({'error': 'school_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(school_id=new_school_id).exclude(pk=student.pk).exists():
        return Response({'error': 'School ID already in use by another account'}, status=status.HTTP_400_BAD_REQUEST)

    student.school_id = new_school_id
    student.save(update_fields=['school_id'])
    log_activity(user, 'student_school_id_updated', f'Dean {user.username} updated school_id for student {student.username} to {new_school_id}', request)
    send_student_verification_update(user.department, 'school_id_updated', student.id, {'school_id': student.school_id})
    return Response({'message': 'School ID updated', 'school_id': student.school_id})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_enrolled_students(request):
    """List all enrolled students — dean only, filtered by their department"""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, status=status.HTTP_403_FORBIDDEN)

    search = request.GET.get('search', '').strip()
    qs = EnrolledStudent.objects.filter(department=user.department)
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(school_id__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )

    return Response([{
        'id': r.id,
        'school_id': r.school_id,
        'first_name': r.first_name,
        'last_name': r.last_name,
        'department': r.department,
        'year_level': r.year_level,
        'email': r.email,
        'contact_number': r.contact_number,
        'added_at': r.added_at.isoformat(),
    } for r in qs])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_enrolled_student(request):
    """Manually add a single enrolled student record — dean only"""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, status=status.HTTP_403_FORBIDDEN)

    school_id = request.data.get('school_id', '').strip()
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    year_level = request.data.get('year_level', '').strip()
    email = request.data.get('email', '').strip() or None
    contact_number = request.data.get('contact_number', '').strip() or None

    if not all([school_id, first_name, last_name, year_level]):
        return Response({'error': 'school_id, first_name, last_name, and year_level are required'}, status=status.HTTP_400_BAD_REQUEST)

    if EnrolledStudent.objects.filter(school_id=school_id).exists():
        return Response({'error': f'School ID "{school_id}" already exists in enrollment records'}, status=status.HTTP_400_BAD_REQUEST)

    record = EnrolledStudent.objects.create(
        school_id=school_id,
        first_name=first_name,
        last_name=last_name,
        department=user.department,
        year_level=year_level,
        email=email,
        contact_number=contact_number,
    )
    send_enrollment_records_update(user.department, 'created', {'record_id': record.id})
    return Response({'id': record.id, 'message': 'Enrollment record added'}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_enrolled_student(request, record_id):
    """Delete an enrolled student record — dean only"""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, status=status.HTTP_403_FORBIDDEN)

    try:
        record = EnrolledStudent.objects.get(id=record_id, department=user.department)
        deleted_id = record.id
        record.delete()
        send_enrollment_records_update(user.department, 'deleted', {'record_id': deleted_id})
        return Response({'message': 'Record deleted'})
    except EnrolledStudent.DoesNotExist:
        return Response({'error': 'Record not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_enrolled_students_csv(request):
    """Bulk import enrolled students from CSV — dean only"""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, status=status.HTTP_403_FORBIDDEN)

    if 'file' not in request.FILES:
        return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

    csv_file = request.FILES['file']
    if not csv_file.name.lower().endswith('.csv'):
        return Response({'error': 'File must be a CSV'}, status=status.HTTP_400_BAD_REQUEST)

    import csv
    import io

    try:
        decoded = csv_file.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))
        reader.fieldnames = [f.strip() for f in (reader.fieldnames or [])]

        success_count = 0
        error_count = 0
        errors = []

        for row_num, row in enumerate(reader, start=2):
            row = {k: (v.strip() if v else v) for k, v in row.items()}
            required = ['school_id', 'first_name', 'last_name', 'year_level']
            missing = [f for f in required if not row.get(f)]
            if missing:
                errors.append({'row': row_num, 'error': f'Missing: {", ".join(missing)}'})
                error_count += 1
                continue

            year_map = {'1st': '1', '2nd': '2', '3rd': '3', '4th': '4', '1': '1', '2': '2', '3': '3', '4': '4'}
            if row['year_level'] not in year_map:
                errors.append({'row': row_num, 'error': f'Invalid year_level "{row["year_level"]}"'})
                error_count += 1
                continue

            if EnrolledStudent.objects.filter(school_id=row['school_id']).exists():
                errors.append({'row': row_num, 'error': f'School ID "{row["school_id"]}" already exists'})
                error_count += 1
                continue

            EnrolledStudent.objects.create(
                school_id=row['school_id'],
                first_name=row['first_name'],
                last_name=row['last_name'],
                department=user.department,
                year_level=year_map[row['year_level']],
                email=row.get('email') or None,
                contact_number=row.get('contact_number') or None,
            )
            success_count += 1

        if success_count > 0:
            send_enrollment_records_update(
                user.department,
                'imported',
                {'success_count': success_count},
            )

        return Response({
            'message': f'{success_count} records imported, {error_count} errors',
            'success_count': success_count,
            'error_count': error_count,
            'errors': errors,
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download_enrolled_template(request):
    """Download CSV template for enrolled student import"""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can download this template'}, status=status.HTTP_403_FORBIDDEN)

    import csv
    from django.http import HttpResponse
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="enrolled_students_template.csv"'
    writer = csv.writer(response)
    writer.writerow(['school_id', 'first_name', 'last_name', 'year_level', 'email', 'contact_number'])
    writer.writerow(['2024-001', 'Juan', 'Dela Cruz', '1st', 'juan@example.com', '09123456789'])
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_enrolled_record(request, student_id):
    """Fetch the official enrollment record matching a pending student's school_id for dean verification."""
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, status=status.HTTP_403_FORBIDDEN)

    try:
        student = User.objects.get(id=student_id, department=user.department, role='student')
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    if not student.school_id:
        return Response({'found': False, 'record': None})

    try:
        record = EnrolledStudent.objects.get(school_id=student.school_id)
        return Response({
            'found': True,
            'record': {
                'school_id': record.school_id,
                'first_name': record.first_name,
                'last_name': record.last_name,
                'department': record.department,
                'year_level': record.year_level,
                'email': record.email,
                'contact_number': record.contact_number,
            }
        })
    except EnrolledStudent.DoesNotExist:
        return Response({'found': False, 'record': None})
