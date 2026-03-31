# Gmail SMTP Setup for Password Reset

## Steps to Enable Gmail for Password Reset Emails:

### 1. Enable 2-Factor Authentication on Gmail
1. Go to your Google Account: https://myaccount.google.com/
2. Click on "Security" in the left menu
3. Under "Signing in to Google", enable "2-Step Verification"

### 2. Generate App Password
1. Go to: https://myaccount.google.com/apppasswords
2. Select "Mail" as the app
3. Select "Other (Custom name)" as the device
4. Enter "Django Online Exam" as the name
5. Click "Generate"
6. Copy the 16-character password (remove spaces)

### 3. Update Django Settings
Open `backend/settings.py` and update:

```python
EMAIL_HOST_USER = 'your-actual-email@gmail.com'  # Your Gmail address
EMAIL_HOST_PASSWORD = 'xxxx xxxx xxxx xxxx'  # The 16-char app password from step 2
DEFAULT_FROM_EMAIL = 'Online Exam System <your-actual-email@gmail.com>'
```

### 4. Test the Email
Run the Django server and try the "Forgot Password" feature. The email should now be sent to the user's Gmail inbox.

## Important Notes:
- Never commit your actual email and password to Git
- For production, use environment variables:
  ```python
  import os
  EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
  EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
  ```
- The app password is different from your regular Gmail password
- If emails go to spam, ask users to mark as "Not Spam"

## Troubleshooting:
- If emails don't send, check that 2FA is enabled
- Verify the app password is correct (no spaces)
- Check Django console for error messages
- Ensure your Gmail account allows "Less secure app access" is NOT needed (App Passwords work with 2FA)
