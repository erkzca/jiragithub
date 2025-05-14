import requests
from requests.auth import HTTPBasicAuth
import logging
import re
import os

import config.custom_fields_to_use

# Fetch Jira issues
def fetch_jira_issues(
    jira_base_url: str,
    jira_user: str,
    jira_api_token: str,
    jql: str,
    page_size: int = 100,
) -> list[dict]:
    """Return **all** issues matching *jql*."""
    issues: list[dict] = []
    start_at = 0

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    session.auth = HTTPBasicAuth(jira_user, jira_api_token)

    while True:
        resp = session.get(
            f"{jira_base_url}/rest/api/3/search",
            params={
                "jql": jql,
                "startAt": start_at,
                "maxResults": page_size,
                'fields': '*all'
            },
            timeout=30,
        )
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as err:
            logging.error("Jira search failed: %s - %s", err, resp.text)
            raise

        data = resp.json()
        page = data.get("issues", [])
        issues.extend(page)

        page_len = len(page)
        total = data.get("total", 0)

        if page_len == 0 or start_at + page_len >= total:
            break

        start_at += page_len

    return issues


# Fetch Jira comments
def fetch_all_jira_comments(jira_base_url, jira_user, jira_api_token, issue_key) -> list[dict]:
    start_at = 0
    all_comments = []

    while True:
        url = f"{jira_base_url}/rest/api/3/issue/{issue_key}/comment"
        params = {'startAt': start_at, 'maxResults': 100}
        headers = {'Accept': 'application/json'}
        auth = HTTPBasicAuth(jira_user, jira_api_token)

        response = requests.get(url, headers=headers, auth=auth, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch comments for issue {issue_key}: {response.status_code} - {response.text}")
            break

        data = response.json()
        comments = data.get("comments", [])
        all_comments.extend(comments)

        if start_at + len(comments) >= data.get("total", 0):
            break
        start_at += len(comments)

    return all_comments
    
def fetch_jira_issue_xml(jira_base_url, jira_user, jira_api_token, issue_key):
    
    url = f'{jira_base_url}/si/jira.issueviews:issue-xml/{issue_key}/{issue_key}.xml'
    response = requests.get(url, headers={'Accept': 'application/xml'},
                            auth=HTTPBasicAuth(jira_user, jira_api_token))
    if response.status_code == 200:
        return response.text
    else:
        logging.error("Failed to fetch comments for issue:",
                      issue_key, response.status_code, response.text)
        return []


def get_custom_fields_from_jira(jira_base_url, jira_user, jira_api_token):
    url = f'{jira_base_url}/rest/api/3/field'
    response = requests.get(url, headers={'Accept': 'application/json'},
                            auth=HTTPBasicAuth(jira_user, jira_api_token))

    if response.status_code == 200:
        fields = response.json()
        custom_fields = {field['id']: field['name']
                         for field in fields if field['custom']}
        return custom_fields

    return custom_fields
