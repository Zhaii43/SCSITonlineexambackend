import tempfile
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from audit.models import AuditLog
from notifications.email_utils import send_password_reset_email, send_pre_registration_otp
from notifications.models import Announcement, Notification
from user.models import PasswordResetToken, User


TEST_STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}


@override_settings(
    STORAGES=TEST_STORAGES,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class UserAndNotificationApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._temp_media = tempfile.mkdtemp(dir='.')
        cls._override = override_settings(MEDIA_ROOT=cls._temp_media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        self.student = User.objects.create_user(
            username='student2',
            email='student2@example.com',
            password='StrongPass123!',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='S-2001',
            contact_number='09170000011',
            is_approved=False,
        )
        self.dean = User.objects.create_user(
            username='dean2',
            email='dean2@example.com',
            password='StrongPass123!',
            role='dean',
            department='BSIT',
            school_id='D-2001',
            contact_number='09170000012',
            is_approved=True,
        )
        self.instructor = User.objects.create_user(
            username='teacher2',
            email='teacher2@example.com',
            password='StrongPass123!',
            role='instructor',
            department='BSIT',
            school_id='T-2001',
            contact_number='09170000013',
            is_approved=True,
        )

    def test_login_returns_access_and_refresh_tokens(self):
        approved_student = User.objects.create_user(
            username='loginstudent',
            email='loginstudent@example.com',
            password='StrongPass123!',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='S-2002',
            contact_number='09170000014',
        )
        approved_student.is_approved = True
        approved_student.save(update_fields=['is_approved'])

        response = self.client.post(
            '/api/login/',
            {'username': approved_student.username, 'password': 'StrongPass123!'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertTrue(AuditLog.objects.filter(user=approved_student, action='login').exists())

    def test_login_accepts_school_id_identifier(self):
        approved_student = User.objects.create_user(
            username='schoolidlogin',
            email='schoolidlogin@example.com',
            password='StrongPass123!',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='2024-LOGIN-01',
            contact_number='09170000018',
            is_approved=True,
        )

        response = self.client.post(
            '/api/login/',
            {'username': approved_student.school_id, 'password': 'StrongPass123!'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    def test_password_reset_flow_validates_and_changes_password(self):
        user = User.objects.create_user(
            username='resetstudent',
            email='resetstudent@example.com',
            password='StrongPass123!',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='S-2003',
            contact_number='09170000015',
            is_approved=True,
        )

        with patch('user.views.send_password_reset_email'):
            request_response = self.client.post(
                '/api/password-reset/request/',
                {'email': user.email},
                format='json',
            )

        self.assertEqual(request_response.status_code, 200)
        token = PasswordResetToken.objects.get(user=user)

        verify_response = self.client.post(
            '/api/password-reset/verify-code/',
            {'email': user.email, 'code': token.token},
            format='json',
        )
        self.assertEqual(verify_response.status_code, 200)

        reset_response = self.client.post(
            '/api/password-reset/reset/',
            {'token': token.token, 'new_password': 'EvenStronger123!'},
            format='json',
        )
        self.assertEqual(reset_response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('EvenStronger123!'))

    def test_password_reset_accepts_case_insensitive_email(self):
        user = User.objects.create_user(
            username='resetstudentcase',
            email='resetstudentcase@example.com',
            password='StrongPass123!',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='S-2004',
            contact_number='09170000017',
            is_approved=True,
        )

        with patch('user.views.send_password_reset_email'):
            request_response = self.client.post(
                '/api/password-reset/request/',
                {'email': 'ResetStudentCase@Example.com'},
                format='json',
            )

        self.assertEqual(request_response.status_code, 200)
        token = PasswordResetToken.objects.get(user=user)

        verify_response = self.client.post(
            '/api/password-reset/verify-code/',
            {'email': 'RESETSTUDENTCASE@example.com', 'code': token.token},
            format='json',
        )
        self.assertEqual(verify_response.status_code, 200)

    def test_shared_email_helper_sends_password_reset_email(self):
        user = User.objects.create_user(
            username='mailstudent',
            email='mailstudent@example.com',
            password='StrongPass123!',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='S-2010',
            contact_number='09170000016',
            is_approved=True,
        )

        sent = send_password_reset_email(user, 'ABC123')

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Password Reset Request', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [user.email])

    def test_shared_email_helper_sends_pre_registration_otp(self):
        sent = send_pre_registration_otp('newstudent@example.com', '654321')

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Verify Your Email', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ['newstudent@example.com'])

    def test_upload_documents_requires_student_role(self):
        self.client.force_authenticate(user=self.instructor)
        file_obj = SimpleUploadedFile('id.png', b'fake-image', content_type='image/png')

        response = self.client.post('/api/profile/upload-documents/', {'id_photo': file_obj})

        self.assertEqual(response.status_code, 403)

    def test_student_approval_creates_notification(self):
        self.student.id_photo = 'id_photos/id.jpg'
        self.student.study_load = 'study_loads/load.pdf'
        self.student.id_verified = True
        self.student.save(update_fields=['id_photo', 'study_load', 'id_verified'])

        self.client.force_authenticate(user=self.dean)
        with patch('user.views.send_student_approval_email'), patch('user.views.send_push_notification'):
            response = self.client.post(f'/api/students/{self.student.id}/approve/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_approved)
        self.assertTrue(Notification.objects.filter(user=self.student, type='account_approved').exists())

    def test_masterlist_student_approval_does_not_require_documents(self):
        masterlist_student = User.objects.create_user(
            username='2024-ML-01',
            email='masterliststudent@example.com',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='2024-ML-01',
            contact_number='09170000019',
            account_source='masterlist_import',
            is_approved=False,
        )
        masterlist_student.set_unusable_password()
        masterlist_student.save()

        self.client.force_authenticate(user=self.dean)
        with patch('user.views.send_bulk_import_email'), patch('user.views.send_push_notification'):
            response = self.client.post(f'/api/students/{masterlist_student.id}/approve/', {}, format='json')

        self.assertEqual(response.status_code, 200)
        masterlist_student.refresh_from_db()
        self.assertTrue(masterlist_student.is_approved)
        self.assertTrue(Notification.objects.filter(user=masterlist_student, type='account_approved').exists())

    def test_bulk_import_students_sets_student_id_as_initial_password(self):
        self.client.force_authenticate(user=self.dean)
        csv_content = (
            "school_id,email,first_name,last_name,year_level,course,subjects,contact_number\n"
            "2024-CSV-01,csvstudent@example.com,Csv,Student,1st,BSIT,Math 101|Programming 1,09170000029\n"
        )
        upload = SimpleUploadedFile("students.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post('/api/students/bulk-import/', {'file': upload})

        self.assertEqual(response.status_code, 200)
        imported_student = User.objects.get(school_id='2024-CSV-01')
        self.assertEqual(imported_student.account_source, 'masterlist_import')
        self.assertTrue(imported_student.check_password('2024-CSV-01'))

    def test_notifications_endpoint_returns_user_notifications(self):
        Notification.objects.create(
            user=self.student,
            type='announcement',
            title='Test Announcement',
            message='Hello student',
            link='/dashboard/student',
        )
        self.client.force_authenticate(user=self.student)

        response = self.client.get('/api/notifications/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['unread_count'], 1)
        self.assertEqual(len(response.data['notifications']), 1)

    def test_announcement_creation_notifies_target_students(self):
        self.student.is_approved = True
        self.student.save(update_fields=['is_approved'])
        self.client.force_authenticate(user=self.dean)

        with patch('notifications.views.send_announcement_email'), patch('notifications.views.send_notification'):
            response = self.client.post(
                '/api/notifications/announcements/create/',
                {
                    'title': 'Enrollment Reminder',
                    'message': 'Please review your dashboard.',
                    'target_audience': 'student',
                    'department': 'BSIT',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Announcement.objects.filter(title='Enrollment Reminder').exists())
        self.assertTrue(Notification.objects.filter(user=self.student, type='announcement').exists())
