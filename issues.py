import requests
from requests.auth import HTTPBasicAuth
import time
from datetime import datetime, timedelta, timezone
import re
import pandas as pd
import threading
from queue import Queue
import traceback
import logging
import os
from dotenv import load_dotenv

import config.assignees
import config.custom_fields_to_use
from transformer import date_time_helper
from parser import jira
import endpoint.github

load_dotenv()


def setup_logging():
    # Create timestamp for log file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_dir = 'logs'
    log_filename = f'{log_dir}/migration_log_{timestamp}.log'

    # Ensure the logs directory exists
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler()  # Also log to console
        ]
    )
    return logging.getLogger(__name__)

def request_worker(queue):
    while True:
        item = queue.get()
        if item is None: 
            logging.info("Worker is shutting down.")
            break

        # Unpacking for the method call
        method, github_repo, github_token, title, body, owner, labels, status, callback = item 
        #print(f"Processing request: {method}, Title: {title}")
        try:
            logging.info(f"Processing request: {method.__name__}, Title: {title}")
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
                response = endpoint.github.make_github_request(requests.post, url, headers=headers, json=json_data)  

                logging.info(f"Response received for create_github_issue: {response.status_code}")
            elif method.__name__ == 'add_issue_to_project':
                # Construct the URL for adding an issue
                logging.info(f"Adding issue to project")
                endpoint.github.add_issue_to_project(github_repo, github_token, title, body)

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
                logging.info("Queue is empty. Worker is waiting for new requests...")
                wait_time = 5
                time.sleep(wait_time)  # Wait for new requests
                break


def slow_down_request(method, github_repo, github_token, title = None, body = None, owner = None, labels = None, status = None, callback=None):
    logging.info(f"Adding request to queue: {method.__name__}, Title: {title}")
    request_queue.put((method, github_repo, github_token, title, body, owner, labels, status, callback)) 
    logging.info(f"Current queue size: {request_queue.qsize()}")  # Check the size of the queue

def parse_reset_time(error_message):
    # Extract timestamp from GitHub error message
    match = re.search(r'timestamp (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)', error_message)
    if match:
        reset_time = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S UTC')
        reset_time = reset_time.replace(tzinfo=timezone.utc)
        return reset_time.timestamp()
    return None


# Fetch Jira issues
def fetch_jira_issues(jira_base_url, jira_user, jira_api_token, jql):
    issues = []
    start_at = 0
    max_results = 100
    while True:
        url = f'{jira_base_url}/rest/api/3/search'
        query = {
            'jql': jql,
            'startAt': start_at,
            'maxResults': max_results,
            'fields': '*all'
        }
        response = requests.get(
            url,
            headers={'Accept': 'application/json'},
            params=query,
            auth=HTTPBasicAuth(jira_user, jira_api_token)
        )
        if response.status_code != 200:
            logging.error(f"Failed to fetch issues: {response.status_code} {response.text}")
            exit()
        data = response.json()
        issues.extend(data.get('issues', []))
        total = data.get('total', 0)
        if start_at + max_results >= total:
            break
        start_at += max_results
    return issues

def parse_issue_attachments(attachments):
    if not attachments:
        return []
    
    attachment_list = []
    for attachment in attachments:
        attachment_name = attachment.get('filename', '')
        attachment_url = attachment.get('content', '')
        if attachment_name and attachment_url:
            attachment_list.append(f"[{attachment_name}]({attachment_url})")
    
    if attachment_list:
        return "\n ## Attachments\n"+'\n'.join(attachment_list)
    return []

def parse_issue_links(content):
    if not content:
        return []
   
    grouped_links = {}

    try:
        for link in content:
            # Handle inwardIssues
            inward_issue = link.get("inwardIssue")
            if inward_issue:
                inward_key = inward_issue.get("key", "")
                inward_summary = inward_issue.get("fields", {}).get("summary", "")
                inward_linked_text = f"[{inward_key} - {inward_summary}]({inward_issue.get('self', '')})"

                # Using the inward relationship name
                inward_relationship = link.get("type", {}).get("inward", "")

                if inward_relationship not in grouped_links:
                    grouped_links[inward_relationship] = []

                grouped_links[inward_relationship].append(inward_linked_text)

            # Handle outwardIssues
            outward_issue = link.get("outwardIssue")
            if outward_issue:
                outward_key = outward_issue.get("key", "")
                outward_summary = outward_issue.get("fields", {}).get("summary", "")
                outward_linked_text = f"[{outward_key} - {outward_summary}]({outward_issue.get('self', '')})"

                # Using the outward relationship name
                outward_relationship = link.get("type", {}).get("outward", "")

                if outward_relationship not in grouped_links:
                    grouped_links[outward_relationship] = []

                grouped_links[outward_relationship].append(outward_linked_text)

    except (AttributeError, KeyError, TypeError) as e:
        logging.error(f"Error parsing links: {e}")
        return "Error parsing links"

    # Prepare output with headings and grouped links
    output = []
    for relationship, links in grouped_links.items():
        if links:  # Only show the relationship if there are links
            output.append(f"{relationship}:")  # Include the relationship as a heading
            output.extend(links)  # Add the links below the relationship heading
    if output:
        return '\n## Linked issues\n' + '\n'.join(output)
    return []


# Fetch Jira comments
def fetch_jira_comments(jira_base_url, jira_user, jira_api_token, issue_key):
    url = f'{jira_base_url}/rest/api/3/issue/{issue_key}/comment'
    response = requests.get(url, headers={'Accept': 'application/json'},
                            auth=HTTPBasicAuth(jira_user, jira_api_token))
    if response.status_code == 200:
        return response.json().get('comments', [])
    else:
        logging.error("Failed to fetch comments for issue:", issue_key, response.status_code, response.text)
        return []



def get_custom_fields_from_jira(jira_base_url, jira_user, jira_api_token):
    url = f'{jira_base_url}/rest/api/3/field'
    response = requests.get(url, headers={'Accept': 'application/json'},
                            auth=HTTPBasicAuth(jira_user, jira_api_token))

    if response.status_code == 200:
        fields = response.json()
        custom_fields = {field['id']: field['name'] for field in fields if field['custom']}
        return custom_fields

    return custom_fields

def read_csv_file():
    df = pd.read_csv('list.csv')
    return df

def compare_csv_to_jira(labels, label_sheet):
    labels_to_remove = label_sheet.loc[label_sheet['Oprettes, som label i GitHub\n[JA/NEJ]'] == 'NEJ','Labels'].tolist()
    filtered_label_list = [label for label in labels if label not in labels_to_remove]
    filtered_label_as_comment = [label for label in labels if label in labels_to_remove]
    return filtered_label_list, filtered_label_as_comment

def filter_custom_fields(fields, custom_fields):
    formatted_fields = []

    for field_id, field_name in custom_fields.items():
        value = fields.get(field_id)
        if value is not None and value != '' and field_id in config.custom_fields_to_use.fields:
            if isinstance(value, dict) and 'displayName' in value:
                display_name_value = value['displayName']
                formatted_fields.append(f"{field_name}: {display_name_value}")
            elif isinstance(value, dict) and 'type' in value and 'content' in value:
                    # Extract the text from the structured content
                    text_content = ""
                    for block in value['content']:
                        if 'content' in block:
                            # Iterate through paragraph's content to get text
                            for paragraph in block['content']:
                                if 'text' in paragraph:
                                    text_content += paragraph['text'] + " "  # Add space between texts
                    if text_content.strip():  # Check if there's any extracted text
                        formatted_fields.append(f"{field_name}: {text_content.strip()}")
            # If it's not a dict, handle other types as necessary (e.g., string)
            elif isinstance(value, str) or value:
                formatted_fields.append(f"{field_name}: {value}")
    result_string = "\n".join(formatted_fields)
    if not result_string:
        return []
    else:
        return "\n ## Brugerdefineret felt\n" + result_string 


def process_content(item, output):
    """ Helper function to process different item types """
    if item['type'] == 'mention':
        mention = item['attrs']['text'].replace('@', '')
        output.append(f"{mention} ")
    elif item['type'] == 'text':
        text = item['text']
        text_with_mentions = re.sub(r'@(\w+)', r'\1', text)  # Remove "@" for mentions

        # Check if the text has marks
        if 'marks' in item and item['marks']:
            formatted_text = text_with_mentions
            has_strong = any(mark['type'] == 'strong' for mark in item['marks'])
            has_em = any(mark['type'] == 'em' for mark in item['marks'])
            has_underline = any(mark['type'] == 'underline' for mark in item['marks'])
            has_link = any(mark['type'] == 'link' for mark in item['marks'])
            
            # Apply basic formatting (bold, italic)
            if has_strong:
                formatted_text = f"**{formatted_text}**"
            if has_em:
                formatted_text = f"*{formatted_text}*"
            
            # Apply underline (HTML tag)
            if has_underline:
                formatted_text = f"<ins>{formatted_text}</ins>"
                
            # Apply link (should be last as it modifies the structure)
            if has_link:
                for mark in item['marks']:
                    if mark['type'] == 'link':
                        href = mark['attrs']['href']
                        formatted_text = f"[{formatted_text}]({href})"
                        break
                        
            output.append(formatted_text)
        else:
            output.append(text_with_mentions)  # Plain text
    elif item['type'] == 'hardBreak':
        output.append('\n')  # Use for new line
    elif item['type'] == 'inlineCard':
        url = item['attrs'].get('url', '')
        output.append(f"[Link]({url})")  # Add link
    elif item['type'] == 'emoji':
        emoji_text = item['attrs'].get('text', '')
        output.append(emoji_text)

def format_ordered_list(block, output, level=1):
    """Format ordered lists with proper nesting and indentation."""
    start_order = 1
    if 'attrs' in block:
        start_order = block['attrs'].get('order', 1)
    
    for index, list_item in enumerate(block['content'], start=start_order):
        # Create prefix with proper indentation
        indent = "   " * (level - 1)  # 2 spaces per level
        item_prefix = f"{indent}{index}. "
        
        if 'content' not in list_item:
            continue
            
        # Process the content of this list item
        for content_block in list_item['content']:
            if content_block['type'] == 'paragraph':
                paragraph_text = []
                for item in content_block.get('content', []):
                    if 'type' in item:
                        if item['type'] == 'text':
                            paragraph_text.append(item.get('text', ''))
                        # Handle other types as needed
                
                if paragraph_text:
                    output.append(f"{item_prefix}{''.join(paragraph_text)}")
            
            # Handle nested ordered lists
            elif content_block['type'] == 'orderedList':
                # Add the parent list item first if not already added
                if not output or not output[-1].startswith(item_prefix):
                    output.append(f"{item_prefix}")
                
                # Process nested list with increased indentation level
                format_ordered_list(content_block, output, level + 1)
    
    # Add blank line after the list
    if output and output[-1] != '':
        output.append('')

def format_bullet_list(block, output, level=1):
    """Format bullet lists with proper nesting and indentation."""
    
    for list_item in block['content']:
        # Create prefix with proper indentation
        indent = "  " * (level - 1)  # 2 spaces per level
        item_prefix = f"{indent}* "
        
        if 'content' not in list_item:
            continue
            
        # Process the content of this list item
        for content_block in list_item['content']:
            if content_block['type'] == 'paragraph':
                paragraph_text = []
                for item in content_block.get('content', []):
                    if 'type' in item:
                        process_content(item, paragraph_text)
                
                if paragraph_text:
                    output.append(f"{item_prefix}{''.join(paragraph_text)}")
            
            # Handle nested bullet lists
            elif content_block['type'] == 'bulletList':
                # Add the parent list item first if not already added
                if not output or not output[-1].startswith(item_prefix):
                    output.append(f"{item_prefix}")
                
                # Process nested list with increased indentation level
                format_bullet_list(content_block, output, level + 1)

def format_jira_comment(comment):
    # Extract the author's display name
    author = comment.get('author', {}).get('displayName', 'Unknown Author') 

    # Handle both direct and nested comment structures
    if 'body' in comment and 'content' in comment['body']:
        content = comment['body']['content']
    elif 'content' in comment:
        content = comment['content']
    else:
        content = []  # Ensure content is defined even if empty

    formatted_parts = []

    href = comment.get('author', {}).get('self')
    # Construct the header part with author
    formatted_parts.append(f"[{author}]({href})\n")

    # Process the content of the comment
    for block in content:
        if block['type'] == 'paragraph' and 'content' in block:
            paragraph_text = []
            for item in block['content']:
                # Process each item within the paragraph
                process_content(item, paragraph_text)
            formatted_text = ''.join(paragraph_text).strip()
            if formatted_text:
                formatted_parts.append(formatted_text)

        elif block['type'] == 'blockquote' and 'content' in block:
            blockquote_text = ["> "]  # Start blockquote with markdown indicator

            for paragraph in block['content']:
                if paragraph['type'] == 'orderedList' and 'content' in paragraph:
                    for index, list_item in enumerate(paragraph['content'], start=paragraph['attrs'].get('order', 1)):
                        list_item_text = []
                        list_item_text.append(f"{index}. ")  # Use index for ordered number

                        for item in list_item['content']:
                            if 'content' in item:
                                for par in item['content']:
                                    process_content(par, list_item_text)

                        formatted_text = ''.join(list_item_text).strip()
                        if formatted_text:
                            blockquote_text.append(formatted_text)
                    blockquote_text.append('\n')  # New line after list in blockquote

                elif paragraph['type'] == 'paragraph' and 'content' in paragraph:
                    for item in paragraph['content']:
                        process_content(item, blockquote_text)
                    blockquote_text.append('\n')  # New line for each paragraph in blockquote

            formatted_text = ''.join(blockquote_text).strip()
            if formatted_text:
                formatted_parts.append(formatted_text)  # Append the formatted blockquote
            formatted_parts.append('')  # Adding an empty line after the blockquote

        elif block['type'] == 'orderedList' and 'content' in block:
            format_ordered_list(block, formatted_parts)  # Use helper function for ordered lists
        elif block['type'] == 'bulletList' and 'content' in block:
            format_bullet_list(block, formatted_parts) 

    # Final formatted output
    return '\n'.join(formatted_parts)

# Migrate Jira issues to GitHub
def migrate_jira_to_github(jira_base_url, jira_user, jira_api_token, github_repo, github_token, jql, projects, assignees):
    # Step 1: Fetch Jira Issues
    jira_issues = fetch_jira_issues(jira_base_url, jira_user, jira_api_token, jql)

    # Step 2: Read csv file
    label_sheet = read_csv_file()

    # Step 3: Process custom fields
    fields = get_custom_fields_from_jira(jira_base_url, jira_user, jira_api_token)
    description =[]

    github_issue_numbers = []
    # resume = False
    # Step 4: Iterate through each issue and create GitHub issues
    for issue in jira_issues:
        # Creation of issue title
        # if issue["id"] == '12100':
        #     resume = True
        # if not resume:
        #     continue
        issue_title = "[" + issue['key'] + "] " + issue['fields']['summary']

        # Creation of issue description
        issue_description = jira.parse_jira_description(issue['fields'].get('description', 'No description found'))

        # Getting owners name from response
        issue_owner = issue['fields']['reporter']['displayName']

        if type(issue['fields']['assignee']) == dict:
        # Getting assignee name from response
            issue_assignee = issue['fields']['assignee']['displayName'].strip()
        else:
            issue_assignee = 'No Assignee'

        # Match the assignee with the Github user to assign the issue to the correct user
        login_user = assignees.get(issue_assignee)


        # Check if that user exists in the assignees dictionary if it does not we add him to the end of the description
        if login_user:
            print(f"The login user is: {login_user}")
        else:
            description.append(f'Assignee: {issue_assignee}')
            print(f"No matching login found. {issue_assignee}")
        
        # Getting the issue created date from response
        issue_created = date_time_helper.convert_jira_to_github_datetime_format(issue['fields']['created'])

        # Getting the issue custom fields from response
        issue_fields = filter_custom_fields(issue['fields'], fields)

        # Getting the issue attachments from response
        issue_attachments = parse_issue_attachments(issue['fields'].get('attachment', []))

        # Appending main body of description to the description list
        description.append(issue_description)

        # Getting issue links from response (The relationship between issues) e.g. "is blocked by" or "blocks"
        issue_links = parse_issue_links(issue['fields'].get('issuelinks', []))

        # If any of them exist we add them to the body of the description
        if issue_links:
            description.append(issue_links)
        if issue_attachments:
            description.append(issue_attachments)
        if issue_fields:   
            description.append(issue_fields)

        # Converting from list to string
        final_description = "\n".join([str(item) for item in description])

        # Getting issue labels from response
        issue_labels = issue['fields'].get('labels', [])

        # Comparing the labels from the response with the labels in the csv file
        label_list, labels_as_comment = compare_csv_to_jira(issue_labels, label_sheet)
        
        # Getting issue priority from response
        issue_priority = issue['fields']['priority']['name']

        # Appending the issue priority to the label list as per requirement
        label_list.append(issue_priority)

        # Appending the issue owner to the label list as per requirement
        label_list.append(issue_owner)

        # Getting issue status from response
        issue_status = issue['fields']['status']['name']

        # Based on different status we set the issue status to True or False and append the status to the label list
        if issue_status == 'Reopened':
            issue_status = False
            label_list.append('Reopened')
        elif issue_status == 'Closed':
            issue_status = True
        elif issue_status == 'Onhold':
            issue_status = True
            label_list.append('Onhold')
        elif issue_status == 'Resolved':
            issue_status = False
            label_list.append('Resolved')
        elif issue_status == 'Open':
            issue_status = False
        
        # Getting the type of issue from response e.g. "Bug" or "Task"
        issue_type = issue['fields']['issuetype']['name']

        # Fetching the comments from the issue
        issue_comments = fetch_jira_comments(jira_base_url, jira_user, jira_api_token, issue['key'])
        comment_created_date = []
        formatted_comments = []
        # Formatting the comments to be added to the issue
        for comment in issue_comments:
           formatted_comments.append(format_jira_comment(comment))
           comment_created_date.append(date_time_helper.convert_jira_to_github_datetime_format(comment['created']))
        if issue_type == 'Bug':
            label_list.append('bug')

        comments_list = []
        for i in range(len(formatted_comments)):
            comments_list.append({
                "body": formatted_comments[i],
                "created_at": comment_created_date[i]
            })
        issue_number = endpoint.github.create_github_issue(github_repo, github_token, issue_title, final_description, login_user, label_list, issue_status, issue_created, comments_list) 
        github_issue_numbers.append(issue_number)

    return github_issue_numbers

def get_project_id(projects: list[dict], project_name:str) -> str:
    for project in projects:
        if project['title'] == "JAR":
            return project['id']
        else:
            raise ValueError(f"Project '{project_name}' not found in the list of projects.")
        
if __name__ == "__main__":

    JIRA_BASE_URL = os.getenv('JIRA_BASE_URL')
    JIRA_USER = os.getenv('JIRA_USER')
    JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
    GH_REPO = os.getenv('GH_REPO')
    GH_TOKEN = os.getenv('GH_TOKEN')
    PROJECT_KEY = os.getenv('PROJECT_KEY')
    JQL = os.getenv('JQL')

    logger = setup_logging()
    # request_queue = Queue()
    # worker_thread = threading.Thread(target=request_worker,args=(request_queue,))
    # worker_thread.start()

    # Fetch Github projects that exist in working repo (Working on your own repo you can comment this out)
    projects = endpoint.github.list_projects(GH_REPO, GH_TOKEN)

    # Jar github projects to migrate to (The ones that exist in JAR Github repository)
    projects_to = ['JAR'] #['TEST - Lokal RSjælland', 'TEST - Lokal RSyd', 'TEST - JAR-MASTER']

    #Function tp start the migration process
    github_issue_numbers = migrate_jira_to_github(JIRA_BASE_URL, JIRA_USER, JIRA_API_TOKEN, GH_REPO, GH_TOKEN, JQL, projects_to, config.assignees.ASSIGNEES)

    # Add issue to project (TEST - JAR-MASTER) in GitHub
    project_id = get_project_id(projects, project_name="JAR")

    # Number provided there is the created issue number in GitHub
    for issue_number in github_issue_numbers:
        # if issue_number is not None:
        # Add the issue to the project
        endpoint.github.add_issue_to_project(GH_REPO, GH_TOKEN, project_id, issue_number)

    # Bigger jql to be able to get more issues from Jira
    # jql_jira = ['project = "Region Sjælland"', 'project = Region Syddanmark', 'project = JAR and labels IN (4.0, 4.01, 4.1, 4.2, 4.7, 4.12, UdenforRelease, Uafklaret)' ]
    # worker_thread.join()  # Wait for the worker thread to finish
