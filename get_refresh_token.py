"""
get_refresh_token.py
Run this ONCE, locally, on your own machine (not in CI) to authorize the app
against your Gmail account and print a refresh token.

Prereqs:
  1. In Google Cloud Console, create a project, enable the "Gmail API", and
     create an OAuth Client ID of type "Desktop app".
  2. Download the credentials JSON and save it as `credentials.json` next to
     this script.

Usage:
  pip install google-auth-oauthlib google-api-python-client
  python get_refresh_token.py
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n--- Save these as GitHub repo secrets ---")
    print(f"GMAIL_CLIENT_ID={creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("------------------------------------------")


if __name__ == "__main__":
    main()
