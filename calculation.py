import requests
from requests.auth import HTTPBasicAuth
import time
from datetime import datetime, timezone
import re
import pandas as pd
import threading
from queue import Queue
import traceback


def fetch_jira_issues(jira_url, jira_user, jira_api_token, jql):
    url = f'{jira_url}/rest/api/3/search'
    query = {
    'jql': f'{jql}',
    'startAt': 0,
    'maxResults': 100,
    'fields': '*all'
    }
    response = requests.get(url, headers={'Accept': 'application/json'},
                            params=query, auth=HTTPBasicAuth(jira_user, jira_api_token))
    if response.status_code == 200:
        return response.json().get('issues', [])
    else:
        print("Failed to fetch issues:", response.status_code, response.text)
        exit()

def fetch_jira_comments(jira_url, jira_user, jira_api_token, issue_key):
    url = f'{jira_url}/rest/api/3/issue/{issue_key}/comment'
    response = requests.get(url, headers={'Accept': 'application/json'},
                            auth=HTTPBasicAuth(jira_user, jira_api_token))
    if response.status_code == 200:
        return response.json().get('comments', [])
    else:
        print("Failed to fetch comments for issue:", issue_key, response.status_code, response.text)
        return []

def calculate_api_calls(jira_url, jira_user, jira_api_token, jql):
    issues = fetch_jira_issues(jira_url, jira_user, jira_api_token, jql)
    # print(issues)
    comments = []
    for issue in issues:
        comments.extend(fetch_jira_comments(jira_url, jira_user, jira_api_token, issue['key']))
    print(len(issues) + len(comments))
    return len(issues) + len(comments)

jira_url = 'https://jar-cowi.atlassian.net'
jira_user = ''
jira_api_token = ''
github_repo = 'Danske-Regioner-Miljoe-Tvaerregional/JAR-TEST-REPO'
github_token = ''
project_key = 'JAR'
jql = 'project = JAR and labels = 4.0 or labels = 4.01 or labels = 4.1 or labels = 4.2 or labels = 4.7 or labels = 4.12 or labels = UdenforRelease or labels = “Uafklaret”'

amount = calculate_api_calls(jira_url, jira_user, jira_api_token, jql)
