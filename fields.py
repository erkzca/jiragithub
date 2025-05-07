import requests
from requests.auth import HTTPBasicAuth
import os
from dotenv import load_dotenv

load_dotenv()

def fetch_jira_labels(jira_url, jira_user, jira_api_token):

    response = requests.get(jira_url, headers={'Accept': 'application/json'},
                            auth=HTTPBasicAuth(jira_user, jira_api_token))
    if response.status_code == 200:
        return response.json()
    else:
        print("Failed to fetch labels:", response.status_code, response.text)
        exit()


if __name__ == "__main__":
    # Environment variables
    JIRA_URL = f"{os.getenv('JIRA_BASE_URL')}/rest/api/3/field"
    JIRA_USER = os.getenv('JIRA_USER')
    JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
    jira_labels = fetch_jira_labels(JIRA_URL, JIRA_USER, JIRA_API_TOKEN)
    print(jira_labels)
