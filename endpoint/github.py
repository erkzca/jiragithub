import time
import logging
import requests
from datetime import datetime, timedelta
import traceback

import endpoint.github

last_request_time = 0  # Tracks the last request time

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

def make_github_request(method, url, headers, params=None, json=None, max_retries=3):
    global last_request_time  # Use global variable to track last request time
    github_limiter.wait_if_needed()

    # Determine if the request is a POST, PATCH, PUT, or DELETE
    if method in (requests.post, requests.patch, requests.put, requests.delete):
        current_time = time.time()
        time_since_last_request = current_time - last_request_time
        if time_since_last_request < 1:
            wait_time = max(0.5 - time_since_last_request, 0.0)
            logging.info(f"Waiting {wait_time:.0f} seconds to avoid hitting secondary rate limits...")
            time.sleep(wait_time)

    for attempt in range(max_retries):
        response = method(url, headers=headers, params=params, json=json)
        last_request_time = time.time()  # Update last request time after making the request

        remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
        reset_time = int(response.headers.get('X-RateLimit-Reset', 0))

        if response.status_code in (429, 403):
            error_data = response.json()
            request_id = error_data.get('message', '').split('request ID ')[-1].split()[0]
            logging.warning(f"Rate limit exceeded. Request ID: {request_id}")

            if 'secondary rate limit' in error_data.get('message', ''):
                if response.status_code == 429 or response.status_code == 403:
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        wait_time = int(retry_after)
                    else:
                        wait_time = max(reset_time - time.time(), 60)
                    logging.warning(f"Secondary rate limit hit. Waiting {wait_time:.0f} seconds...")
                    time.sleep(wait_time)
                else: 
                    wait_time = min(300, 30 * (2 ** attempt))
                    logging.warning(f"Secondary rate limit hit. Backing off for {wait_time:.0f} seconds...")
                    time.sleep(wait_time)
                continue

        if remaining < 5:
            wait_time = reset_time - time.time()
            if wait_time > 0:
                logging.warning(f"Rate limit nearly exhausted. Waiting {wait_time:.0f} seconds...")
                time.sleep(wait_time + 1)

        if response.status_code != 403:
            return response

        if attempt < max_retries - 1:
            time.sleep(min(300, 30 * (2 ** attempt)))

    return response

# Create a new GitHub issue
def create_github_issue(github_repo, github_token,
    issue_title, final_description,
    issue_owner, label_list,
    issue_status, issue_created,
    comments_list,
    poll_interval=0.5,   # seconds between polls
    poll_timeout=30): # give up after N seconds

    if len(final_description)> 65000:
        logging.warning(f"Description too long ({len(final_description)}). Truncating to 65000 characters.")
        final_description = final_description[:65000]

    # 1) Create the issue
    url = f"https://api.github.com/repos/{github_repo}/import/issues"
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.golden-comet-preview+json',
        'Content-Type': 'application/json'
    }
    payload = {
        "issue": {
            "title": issue_title,
            "body": final_description, # truncate to GitHub issue body max length
            "created_at": issue_created,
            "closed": issue_status,
            # "assignee": issue_owner, #NOTE uncomment for prod
            "labels": label_list
        },
        "comments": comments_list[:100], # limit to 100 comments
    }

    response = make_github_request(requests.post, url, headers=headers, json=payload)

    # 1) If they let us create immediately (unlikely for import), handle 201:
    if response.status_code == 201:
        issue_number = response.json().get('number')
        logging.info(f"GitHub issue created immediately: #{issue_number}")
        return issue_number

    # 2) Handle the async import case
    if response.status_code == 202:
        data = response.json()
        import_id     = data['id']
        status_url    = data['url']
        logging.info(f"Issue import queued (job {import_id}). Polling {status_url}…")

        # Poll until done or timeout
        start_time = time.time()
        while True:
            status_resp = make_github_request(requests.get, status_url,
                                              headers=headers)
            status_resp_json = status_resp.json()
            status = status_resp_json.get('status')

            if status in ('imported', 'failed'):
                break

            if time.time() - start_time > poll_timeout:
                logging.error("Polling timed out.")
                return None

            logging.debug(f"Import job {import_id} still pending…")
            time.sleep(poll_interval)

        if status == 'imported':
            issue_number = status_resp_json["issue_url"].split("/")[-1]

            if len(comments_list) > 100:
                logging.error(f"Comments list is too long ({len(comments_list)}). Splitting into batches of 100.")
                for lower_bound in range(100, len(comments_list), 100):
                    comments_list_batch = comments_list[lower_bound:lower_bound+100]

                    comment_resp = requests.post(
                    f"https://api.github.com/repos/{github_repo}/issues/{issue_number}/comments",
                    headers=headers,
                    json=comments_list_batch
                    )
                    comment_resp.raise_for_status()
                    time.sleep(1)
            logging.info(f"Issue number #{issue_number} succeeded.")
            return issue_number

        # status == 'failed'
        logging.error(f"Issue import #{import_id} failed: {status_resp_json}")
        return None

    # 3) Any other status is an error
    logging.error(f"Failed to start issue import: {response.status_code} {response.text}")
    return None

def list_projects(github_repo, github_token):
    owner, repo = github_repo.split('/')
    
    query = """
    query($owner: String!, $repo: String!) {
        repository(owner: $owner, name: $repo) {
            projectsV2(first: 100) {
                nodes {
                    id
                    number
                    title
                }
            }
        }
    }
    """
    
    variables = {'owner': owner, 'repo': repo}
    
    response = make_github_request(
        requests.post,
        "https://api.github.com/graphql",
        headers={
            'Authorization': f'Bearer {github_token}',
            'Content-Type': 'application/json',
        },
        json={'query': query, 'variables': variables}
    )
    if response.status_code == 200:
        data = response.json()
        return data.get('data', {}).get('repository', {}).get('projectsV2', {}).get('nodes', [])
    return []

def add_issue_to_project(github_repo, github_token, project_id, issue_number):
    owner, repo = github_repo.split('/')
    
    # First get issue node ID using GraphQL
    issue_query = """
    query($owner: String!, $repo: String!, $number: Int!) {
        repository(owner: $owner, name: $repo) {
            issue(number: $number) {
                id
            }
        }
    }
    """
    
    variables = {
        'owner': owner,
        'repo': repo,
        'number': int(issue_number)
    }
    
    # Get issue node ID
    response = make_github_request(
        requests.post,
        "https://api.github.com/graphql",
        headers={
            'Authorization': f'Bearer {github_token}',
            'Content-Type': 'application/json',
        },
        json={'query': issue_query, 'variables': variables}
    )
    
    if response.status_code != 200:
        logging.error(f"Failed to get issue node ID: {response.status_code}")
        return False
        
    issue_node_id = response.json().get('data', {}).get('repository', {}).get('issue', {}).get('id')
    if not issue_node_id:
        logging.error("Could not find issue node ID")
        return False
    
    # Add issue to project using mutation
    mutation = """
    mutation($projectId: ID!, $contentId: ID!) {
        addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
            item {
                id
            }
        }
    }
    """
    
    variables = {
        'projectId': project_id,
        'contentId': issue_node_id
    }
    
    response = make_github_request(
        requests.post,
        "https://api.github.com/graphql",
        headers={
            'Authorization': f'Bearer {github_token}',
            'Content-Type': 'application/json',
        },
        json={'query': mutation, 'variables': variables}
    )
    logging.info(f"Response received for add_issue_to_project: {response.status_code}")
    success = response.status_code == 200 and 'errors' not in response.json()
    if success:
        logging.info(f"Added issue #{issue_number} to project")
    else:
        logging.error(f"Failed to add issue to project: {response.text}")
    
    return success

def request_worker(queue):
    while True:
        item = queue.get()
        if item is None:
            logging.info("Worker is shutting down.")
            break

        # Unpacking for the method call
        method, github_repo, github_token, title, body, owner, labels, status, callback = item
        # print(f"Processing request: {method}, Title: {title}")
        try:
            logging.info(
                f"Processing request: {method.__name__}, Title: {title}")
            if method.__name__ == 'create_github_issue':
                # Construct the URL for creating the GitHub issue
                logging.info(f"Creating GitHub issue")
                url = f"https://api.github.com/repos/{github_repo}/issues"
                headers = {
                    'Authorization': f'Bearer {github_token}',
                    'Accept': 'application/vnd.github.v3+json',
                    'Content-Type': 'application/json'
                }

                # Prepare JSON payload for the GitHub issue
                json_data = {
                    'title': title,
                    'body': body,
                    'labels': labels,
                }

                # Call make_github_request correctly for creating issues
                response = endpoint.github.make_github_request(
                    requests.post, url, headers=headers, json=json_data)

                logging.info(
                    f"Response received for create_github_issue: {response.status_code}")
            elif method.__name__ == 'add_issue_to_project':
                # Construct the URL for adding an issue
                logging.info(f"Adding issue to project")
                endpoint.github.add_issue_to_project(
                    github_repo, github_token, title, body)

            # Execute callback if provided
            if callback:
                logging.info("Executing callback...")
                callback(response.json())
        except Exception as e:
            logging.error("An error occurred in request_worker:")
            traceback.print_exc()
        finally:
            queue.task_done()
            if queue.empty():
                logging.info(
                    "Queue is empty. Worker is waiting for new requests...")
                wait_time = 5
                time.sleep(wait_time)  # Wait for new requests
                break