import requests
from requests.auth import HTTPBasicAuth
import time
from datetime import datetime, timezone
import re

class GithubRateLimiter:
    def __init__(self, max_requests=30, time_window=60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    def wait_if_needed(self):
        now = datetime.now()
        self.requests = [req_time for req_time in self.requests 
                        if (now - req_time).total_seconds() < self.time_window]
        
        if len(self.requests) >= self.max_requests:
            # Wait until oldest request expires
            sleep_time = self.time_window - (now - self.requests[0]).total_seconds()
            if sleep_time > 0:
                time.sleep(sleep_time + 1)  # Add 1 second buffer
            self.requests = self.requests[1:]
        
        self.requests.append(now)

github_limiter = GithubRateLimiter()

def parse_reset_time(error_message):
    # Extract timestamp from GitHub error message
    match = re.search(r'timestamp (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)', error_message)
    if match:
        reset_time = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S UTC')
        reset_time = reset_time.replace(tzinfo=timezone.utc)
        return reset_time.timestamp()
    return None

def make_github_request(method, url, headers, params=None, json=None, max_retries=3):
    github_limiter.wait_if_needed()
    
    for attempt in range(max_retries):
        response = method(url, headers=headers, params=params, json=json)
        remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
        reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
        
        if response.status_code == 403:
            error_data = response.json()
            request_id = error_data.get('message', '').split('request ID ')[-1].split()[0]
            print(f"Rate limit exceeded. Request ID: {request_id}")
            
            # Handle secondary rate limit
            if 'secondary rate limit' in error_data.get('message', ''):
                reset_time = parse_reset_time(error_data['message'])
                if reset_time:
                    wait_time = max(reset_time - time.time(), 60)  # At least 60 seconds
                    print(f"Secondary rate limit hit. Waiting {wait_time:.0f} seconds...")
                    time.sleep(wait_time)
                else:
                    # If can't parse reset time, use exponential backoff with longer delays
                    wait_time = min(300, 30 * (2 ** attempt))  # Max 5 minutes
                    print(f"Secondary rate limit hit. Backing off for {wait_time} seconds...")
                    time.sleep(wait_time)
                continue
                
        if remaining < 5:  # Buffer threshold
            wait_time = reset_time - time.time()
            if wait_time > 0:
                print(f"Rate limit nearly exhausted. Waiting {wait_time:.0f} seconds...")
                time.sleep(wait_time + 1)
        
        if response.status_code != 403:
            return response
            
        if attempt < max_retries - 1:
            time.sleep(min(300, 30 * (2 ** attempt)))  # Cap at 5 minutes
    
    return response


def fetch_jira_projects(jira_url, jira_user, jira_api_token):
    url = f"{jira_url}/rest/api/2/project"
    response = requests.get(url, auth=HTTPBasicAuth(jira_user, jira_api_token))

    if response.status_code == 200:
        return response.json()  # Returns a list of projects
    else:
        print(f"Failed to fetch Jira projects: {response.status_code}, {response.text}")
        return []

def create_github_project(github_repo, github_token, project_name, project_body=None):
    # Split repo into owner/repo
    owner, repo = github_repo.split('/')
    
    # Use repository projects API
    url = f"https://api.github.com/repos/{owner}/{repo}/projects"
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github+json',  # Projects API preview
        'Content-Type': 'application/json'
    }

    payload = {
        'name': project_name,
        'body': project_body if project_body else ''
    }

    # Validate repo exists first
    validate_url = f"https://api.github.com/repos/{owner}/{repo}"
    validate_response = make_github_request(requests.get, validate_url, headers=headers)
    if validate_response.status_code != 200:
        print(f"Repository {github_repo} not found or access denied")
        return None

    response = make_github_request(requests.post, url, headers=headers, json=payload)

    if response.status_code == 201:
        print(f"Created project '{project_name}' successfully in {github_repo}")
        return response.json()
    elif response.status_code == 404:
        print(f"Repository {github_repo} not found or projects not enabled")
        return None
    elif response.status_code == 410:
        print("Projects are disabled. Please enable Projects in repository settings")
        return None
    else:
        print(f"Failed to create project: {response.status_code}, {response.text}")
        return None
     
jira_url = 'https://jar-cowi.atlassian.net'
jira_user = ''
jira_api_token = ''
github_repo = ''
github_token = ''
project_key = 'JAR'

jira_projects = fetch_jira_projects(jira_url, jira_user, jira_api_token)
for jira_project in jira_projects:
    project_name = jira_project['name']  # Use the name from the Jira project
    project_body = f"Project migrated from Jira: {jira_project['key']}"

    create_github_project(github_repo, github_token, project_name, project_body)