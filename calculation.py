import os
from dotenv import load_dotenv
load_dotenv()

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


if __name__ == "__main__":

    # Environment variables
    JIRA_BASE_URL = os.getenv('JIRA_BASE_URL')
    JIRA_USER = os.getenv('JIRA_USER')
    JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
    GH_REPO = os.getenv('GH_REPO')
    GH_TOKEN = os.getenv('GH_TOKEN')
    PROJECT_KEY = os.getenv('PROJECT_KEY')
    JQL = os.getenv('JQL')

    amount = calculate_api_calls(JIRA_BASE_URL, JIRA_USER, JIRA_API_TOKEN, JQL)
