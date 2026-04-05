import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from exams.models import Exam, ExamResult, ExamSession, Question, QuestionIssueMessage, QuestionIssueReport
from notifications.models import Notification
from user.models import User


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
class ExamModelAndApiTests(TestCase):
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
            username='student1',
            email='student1@example.com',
            password='StrongPass123!',
            role='student',
            department='BSIT',
            year_level='1',
            school_id='S-1001',
            contact_number='09170000001',
            id_verified=True,
        )
        self.student.is_approved = True
        self.student.save(update_fields=['is_approved'])
        self.instructor = User.objects.create_user(
            username='teacher1',
            email='teacher1@example.com',
            password='StrongPass123!',
            role='instructor',
            department='BSIT',
            school_id='T-1001',
            contact_number='09170000002',
            is_approved=True,
        )
        self.dean = User.objects.create_user(
            username='dean1',
            email='dean1@example.com',
            password='StrongPass123!',
            role='dean',
            department='BSIT',
            school_id='D-1001',
            contact_number='09170000003',
            is_approved=True,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_exam(self, **overrides):
        defaults = {
            'title': 'Midterm Exam',
            'subject': 'Programming',
            'department': 'BSIT',
            'year_level': '1',
            'exam_type': 'midterm',
            'question_type': 'multiple_choice',
            'scheduled_date': timezone.now() - timedelta(minutes=10),
            'expiration_time': timezone.now() + timedelta(minutes=30),
            'duration_minutes': 60,
            'total_points': 10,
            'passing_score': 7,
            'instructions': 'Answer all questions.',
            'created_by': self.instructor,
            'is_approved': True,
            'retake_policy': 'none',
            'max_attempts': 1,
        }
        defaults.update(overrides)
        return Exam.objects.create(**defaults)

    def create_exam_session(self, exam, student=None):
        return ExamSession.objects.create(exam=exam, student=student or self.student)

    def test_exam_result_grade_boundaries_are_calculated(self):
        exam = self.create_exam(total_points=20)
        result = ExamResult.objects.create(
            exam=exam,
            student=self.student,
            score=15,
            total_points=20,
            answers={},
            is_graded=True,
        )

        self.assertEqual(result.percentage, 75.0)
        self.assertEqual(result.grade, '3.00')
        self.assertEqual(result.remarks, 'Passed')

    def test_submit_exam_grades_multiple_choice_answers(self):
        exam = self.create_exam(total_points=10)
        q1 = Question.objects.create(
            exam=exam,
            question='2 + 2 = ?',
            type='multiple_choice',
            options=['3', '4', '5'],
            correct_answer='4',
            points=5,
            order=1,
        )
        q2 = Question.objects.create(
            exam=exam,
            question='3 + 3 = ?',
            type='identification',
            options=None,
            correct_answer='6',
            points=5,
            order=2,
        )
        session = self.create_exam_session(exam)
        self.authenticate(self.student)

        with patch('exams.views.send_results_published_email'), patch('exams.views.send_push_notification'):
            response = self.client.post(
                f'/api/exams/{exam.id}/submit/',
                {
                    'answers': {str(q1.id): '4', str(q2.id): '6'},
                    'session_token': session.session_token,
                },
                format='json',
                HTTP_X_EXAM_SESSION=session.session_token,
            )

        self.assertEqual(response.status_code, 201)
        result = ExamResult.objects.get(exam=exam, student=self.student)
        self.assertEqual(result.score, 10)
        self.assertEqual(result.grade, '1.00')
        self.assertTrue(Notification.objects.filter(user=self.student, type='result_published').exists())

    def test_submit_exam_requires_matching_active_session(self):
        exam = self.create_exam(total_points=5)
        question = Question.objects.create(
            exam=exam,
            question='Capital of France?',
            type='multiple_choice',
            options=['Paris', 'Rome'],
            correct_answer='Paris',
            points=5,
            order=1,
        )
        self.create_exam_session(exam)
        self.authenticate(self.student)

        response = self.client.post(
            f'/api/exams/{exam.id}/submit/',
            {
                'answers': {str(question.id): 'Paris'},
                'session_token': 'wrong-session-token',
            },
            format='json',
            HTTP_X_EXAM_SESSION='wrong-session-token',
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('session', response.data['error'].lower())

    def test_best_score_retake_policy_keeps_highest_score(self):
        exam = self.create_exam(retake_policy='best_score', max_attempts=2, total_points=10)
        question = Question.objects.create(
            exam=exam,
            question='Select the correct value',
            type='multiple_choice',
            options=['A', 'B'],
            correct_answer='A',
            points=10,
            order=1,
        )
        self.authenticate(self.student)

        first_session = self.create_exam_session(exam)
        self.client.post(
            f'/api/exams/{exam.id}/submit/',
            {
                'answers': {str(question.id): 'B'},
                'session_token': first_session.session_token,
            },
            format='json',
            HTTP_X_EXAM_SESSION=first_session.session_token,
        )
        ExamSession.objects.filter(exam=exam, student=self.student).delete()

        second_session = self.create_exam_session(exam)
        self.client.post(
            f'/api/exams/{exam.id}/submit/',
            {
                'answers': {str(question.id): 'A'},
                'session_token': second_session.session_token,
            },
            format='json',
            HTTP_X_EXAM_SESSION=second_session.session_token,
        )

        latest = ExamResult.objects.filter(exam=exam, student=self.student).order_by('-submitted_at').first()
        self.assertEqual(ExamResult.objects.filter(exam=exam, student=self.student).count(), 2)
        self.assertEqual(latest.score, 10)

    def test_get_exam_for_taking_blocks_expired_exams(self):
        exam = self.create_exam(
            scheduled_date=timezone.now() - timedelta(hours=2),
            expiration_time=timezone.now() - timedelta(minutes=1),
        )
        self.authenticate(self.student)

        response = self.client.get(f'/api/exams/{exam.id}/take/')

        self.assertEqual(response.status_code, 403)
        self.assertIn('expired', response.data['error'].lower())

    def test_issue_report_creation_and_reply_flow(self):
        exam = self.create_exam(total_points=5)
        question = Question.objects.create(
            exam=exam,
            question='Which answer is correct?',
            type='multiple_choice',
            options=['A', 'B'],
            correct_answer='A',
            points=5,
            order=1,
        )
        ExamResult.objects.create(
            exam=exam,
            student=self.student,
            score=5,
            total_points=5,
            answers={str(question.id): 'A'},
            is_graded=True,
        )

        self.authenticate(self.student)
        with patch('exams.views.send_issue_report_email'):
            create_response = self.client.post(
                f'/api/exams/{exam.id}/report-issues/',
                {
                    'question_id': question.id,
                    'issue_type': 'typo',
                    'description': 'There is a typo in the prompt.',
                    'reported_answer': 'A',
                },
                format='json',
            )

        self.assertEqual(create_response.status_code, 201)
        report = QuestionIssueReport.objects.get(exam=exam, student=self.student)
        self.assertEqual(report.status, 'under_review')
        self.assertEqual(QuestionIssueMessage.objects.filter(report=report).count(), 1)

        self.client.force_authenticate(user=self.instructor)
        reply_response = self.client.post(
            f'/api/exams/report-issues/{report.id}/messages/',
            {'message': 'Thanks, we will review this.'},
            format='json',
        )

        self.assertEqual(reply_response.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.status, 'resolved')
        self.assertEqual(QuestionIssueMessage.objects.filter(report=report).count(), 2)

    def test_dean_created_exam_is_auto_approved(self):
        self.authenticate(self.dean)

        with patch('exams.views.send_exam_scheduled_email'), patch('exams.views.send_push_to_users'), patch('exams.views.send_dean_exam_created_email') as mock_dean_email:
            response = self.client.post(
                '/api/exams/create/',
                {
                    'title': 'Dean Exam',
                    'subject': 'Programming',
                    'department': 'BSIT',
                    'year_level': '1',
                    'exam_type': 'quiz',
                    'question_type': 'multiple_choice',
                    'scheduled_date': (timezone.now() + timedelta(days=1)).isoformat(),
                    'duration_minutes': 30,
                    'total_points': 10,
                    'passing_score': 7,
                    'instructions': 'Dean-created exam',
                },
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        exam = Exam.objects.get(id=response.data['exam_id'])
        self.assertTrue(exam.is_approved)
        self.assertEqual(exam.created_by, self.dean)
        self.assertEqual(exam.approved_by, self.dean)
        mock_dean_email.assert_called_once()
        self.assertTrue(Notification.objects.filter(user=self.student, type='exam_scheduled').exists())

    def test_dean_can_import_questions_for_own_exam(self):
        exam = self.create_exam(created_by=self.dean, is_approved=False, approved_by=None, approved_at=None)
        self.authenticate(self.dean)

        csv_content = (
            "question,type,options,correct_answer,points\n"
            "Capital of France?,multiple_choice,Paris|Rome|Berlin,Paris,5\n"
        )
        upload = SimpleUploadedFile("questions.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(
            f'/api/exams/{exam.id}/questions/import/',
            {'file': upload},
            format='multipart',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(exam.questions.count(), 1)

    def test_dean_can_grade_own_exam_result(self):
        exam = self.create_exam(
            created_by=self.dean,
            is_approved=True,
            approved_by=self.dean,
            approved_at=timezone.now(),
            total_points=10,
        )
        question = Question.objects.create(
            exam=exam,
            question='Explain polymorphism.',
            type='essay',
            correct_answer='Varies',
            points=10,
            order=1,
        )
        result = ExamResult.objects.create(
            exam=exam,
            student=self.student,
            score=0,
            total_points=10,
            answers={str(question.id): 'Sample answer'},
            is_graded=False,
        )
        self.authenticate(self.dean)

        with patch('exams.views.send_results_published_email'), patch('exams.views.send_push_notification'):
            response = self.client.post(
                f'/api/exams/result/{result.id}/grade/',
                {'manual_scores': {str(question.id): 8}},
                format='json',
            )

        self.assertEqual(response.status_code, 200)
        result.refresh_from_db()
        self.assertTrue(result.is_graded)
        self.assertEqual(result.score, 8)
