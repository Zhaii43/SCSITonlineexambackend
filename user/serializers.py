from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from PIL import Image
import pytesseract
import io
from .models import User

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)
    study_load = serializers.FileField(required=True)
    id_photo = serializers.ImageField(required=False)
    profile_picture = serializers.ImageField(required=False)
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password', 'password2', 
                 'role', 'department', 'school_id', 'year_level', 'contact_number', 'study_load', 'id_photo', 'profile_picture',
                 'is_transferee', 'is_irregular')

    def validate_id_photo(self, value):
        if not value:
            return value

        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("ID photo must be less than 5MB.")

        allowed_types = ['image/jpeg', 'image/jpg', 'image/png']
        if getattr(value, 'content_type', None) not in allowed_types:
            raise serializers.ValidationError("Only JPG and PNG images are allowed for ID photo.")

        return value

    def validate_study_load(self, value):
        """Validate that the study load document is from SCSIT"""
        if not value:
            raise serializers.ValidationError("Study load document is required.")
        
        # Check file size (max 5MB)
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("File size must be less than 5MB.")
        
        # Check file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf']
        if value.content_type not in allowed_types:
            raise serializers.ValidationError("Only JPEG, PNG, or PDF files are allowed.")
        
        # For images, perform OCR verification
        if value.content_type.startswith('image/'):
            try:
                image = Image.open(value)
                # Extract text from image
                text = pytesseract.image_to_string(image).upper()
                
                # Check for SCSIT identifiers
                required_keywords = ['SCSIT', 'SALAZAR']
                study_load_keywords = ['STUDY LOAD', 'STUDYLOAD', 'ENROLLMENT', 'SUBJECT', 'COURSE']
                
                has_institution = any(keyword in text for keyword in required_keywords)
                has_study_load = any(keyword in text for keyword in study_load_keywords)
                
                if not has_institution:
                    raise serializers.ValidationError(
                        "Document must be from SCSIT (Salazar Colleges of Science and Institute of Technology). "
                        "Please upload a valid SCSIT study load document."
                    )
                
                if not has_study_load:
                    raise serializers.ValidationError(
                        "Document does not appear to be a study load. "
                        "Please upload your official SCSIT study load document."
                    )
                
            except Exception as e:
                raise serializers.ValidationError(
                    "Unable to verify document. Please ensure the image is clear and readable."
                )
        
        return value
    
    def validate(self, attrs):
        email = (attrs.get('email') or '').strip().lower()
        username = attrs.get('username')
        school_id = attrs.get('school_id')
        contact_number = attrs.get('contact_number')

        errors = {}
        if email and User.objects.filter(email__iexact=email).exists():
            errors['email'] = "Email already exists."
        if username and User.objects.filter(username=username).exists():
            errors['username'] = "Username already exists."
        if school_id and User.objects.filter(school_id=school_id).exists():
            errors['school_id'] = "School ID already exists."
        if contact_number and User.objects.filter(contact_number=contact_number).exists():
            errors['contact_number'] = "Contact number already exists."
        if errors:
            raise serializers.ValidationError(errors)

        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        if attrs.get('role') == 'student' and not attrs.get('id_photo'):
            raise serializers.ValidationError({"id_photo": "ID photo is required for student registration."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user
