# Study Load Verification Setup

## Installation Steps

### 1. Install Python packages
```bash
pip install -r requirements.txt
```

### 2. Install Tesseract OCR

#### Windows:
1. Download Tesseract installer from: https://github.com/UB-Mannheim/tesseract/wiki
2. Install to default location (C:\Program Files\Tesseract-OCR)
3. Add to system PATH or set in Django settings

#### Alternative (if Tesseract not available):
If you cannot install Tesseract, you can use a simpler validation by checking file metadata only.

## How It Works

The study load verification checks for:
1. File size (max 5MB)
2. File type (JPEG, PNG, or PDF)
3. OCR text extraction to verify:
   - SCSIT or Salazar institution name
   - Study load related keywords (STUDY LOAD, ENROLLMENT, SUBJECT, COURSE)

## Validation Messages

- "Document must be from SCSIT" - Institution name not found
- "Document does not appear to be a study load" - Missing study load keywords
- "Unable to verify document" - Image quality issues or OCR error
