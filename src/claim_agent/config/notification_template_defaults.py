"""Default strings for claimant notification templates.

Single source of truth for NotificationConfig field defaults and for
``claimant._safe_format`` / OTP fallbacks when a custom template fails to format.
"""

TMPL_RECEIPT_ACKNOWLEDGED_SUBJECT = "Claim {claim_id} acknowledgment"
TMPL_RECEIPT_ACKNOWLEDGED_BODY = (
    "We received and acknowledged your claim {claim_id}."
)
TMPL_DENIAL_LETTER_SUBJECT = "Claim {claim_id} denial letter"
TMPL_DENIAL_LETTER_BODY = (
    "Your claim {claim_id} has been denied."
    " Appeal rights are included in your denial letter."
)
TMPL_FOLLOW_UP_SUBJECT = "Claim {claim_id} follow-up"
TMPL_FOLLOW_UP_BODY = "An update is available for your claim {claim_id}."
TMPL_GENERIC_SUBJECT = "Claim {claim_id} update"
TMPL_GENERIC_BODY = "An update is available for your claim {claim_id}."
TMPL_OTP_EMAIL_SUBJECT = "Your DSAR verification code"
TMPL_OTP_EMAIL_BODY = (
    "Your one-time verification code is: {otp}\n\n"
    "This code expires in {ttl_minutes} minutes. "
    "Do not share it with anyone.\n\n"
    "Reference: {verification_id}"
)
TMPL_OTP_SMS_BODY = (
    "Your DSAR verification code: {otp}. Expires in {ttl_minutes} min."
)
