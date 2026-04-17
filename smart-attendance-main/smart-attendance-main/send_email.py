import os
import threading
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
FROM_EMAIL    = "attendancecollege26@gmail.com"
FROM_NAME     = "SmartAttend"


def send_email(to_email, subject, body):
    try:
        configuration         = sib_api_v3_sdk.Configuration()
        configuration.api_key["api-key"] = BREVO_API_KEY

        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )

        send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
            to=[{"email": to_email}],
            sender={"email": FROM_EMAIL, "name": FROM_NAME},
            subject=subject,
            text_content=body
        )

        response = api_instance.send_transac_email(send_smtp_email)
        print(f"[BREVO API] Sent to {to_email} | id: {response.message_id}")
        return True

    except ApiException as e:
        print(f"[BREVO API] Failed for {to_email}: {e}")
        return False
    except Exception as e:
        print(f"[BREVO API] Error: {e}")
        return False


def send_email_async(to_email, subject, body):
    t = threading.Thread(
        target=send_email,
        args=(to_email, subject, body),
        daemon=True
    )
    t.start()
