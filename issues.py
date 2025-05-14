
from datetime import datetime, timedelta, timezone
import re
import pandas as pd
import logging
import os
from dotenv import load_dotenv

import config.assignees
from transformer import date_time_helper
import parser.jira
import endpoint.github
import endpoint.jira

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


def parse_reset_time(error_message):
    # Extract timestamp from GitHub error message
    match = re.search(
        r'timestamp (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)', error_message)
    if match:
        reset_time = datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S UTC')
        reset_time = reset_time.replace(tzinfo=timezone.utc)
        return reset_time.timestamp()
    return None


def read_csv_file():
    df = pd.read_csv('config/list.csv')
    return df


def match_csv_to_jira(labels: list[str] | list[None], label_sheet: pd.DataFrame) -> list[str] | list[None]:
    '''
    compare lowercase jira labels with the lowercase github labels in the csv file.
    then return matching labels from the csv file with original case, not lowercase.
    '''
    labels_lowercase = [label.lower() for label in labels] 
    label_sheet["Labels_lowercase"] = label_sheet.Labels.str.lower()
    idx_label_match = label_sheet.Labels_lowercase.isin(labels_lowercase)
    csv_labels = label_sheet[idx_label_match].Labels.to_list()

    if len(labels) > 0 and len(csv_labels) == 0:
        logging.warning(
            f"No matching labels found in the CSV file for labels: {labels}")

    return csv_labels


# Migrate Jira issues to GitHub


def migrate_jira_to_github(jira_base_url, jira_user, jira_api_token, github_repo, github_token, jql, assignees):
    # Step 1: Fetch Jira Issues
    jira_issues = endpoint.jira.fetch_jira_issues(
        jira_base_url, jira_user, jira_api_token, jql)

    # Step 2: Read csv file
    label_sheet = read_csv_file()

    # Step 3: Process custom fields
    fields = endpoint.jira.get_custom_fields_from_jira(
        jira_base_url, jira_user, jira_api_token)

    github_issue_numbers = []
    # Step 4: Iterate through each issue and create GitHub issues
    total_issues = len(jira_issues)
    logging.info(f"Starting migration of {total_issues} Jira issues to GitHub")
    for idx, issue in enumerate(jira_issues, start=1):
        logging.info(
            f"Processing Jira issue {idx}/{total_issues}: {issue.get('key', '')}")
        description = []
        issue_title = "[" + issue['key'] + "] " + issue['fields']['summary']

        # Creation of issue description
        issue_description = parser.jira.parse_jira_description(
            issue['fields'].get('description', 'No description found'))

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
            logging.info(f"The login user is: {login_user}")
        else:
            description.append(f'Assignee: {issue_assignee}')
            logging.warning(
                f"No matching login found for assignee: {issue_assignee}")

        # Getting the issue created date from response
        issue_created = date_time_helper.convert_jira_to_github_datetime_format(
            issue['fields']['created'])

        # Getting the issue custom fields from response
        issue_fields = parser.jira.filter_custom_fields(issue['fields'], fields)

        # Getting the issue attachments from response
        issue_attachments = parser.jira.parse_issue_attachments(
            issue['fields'].get('attachment', []))

        # Appending main body of description to the description list
        description.append(issue_description)

        # Getting issue links from response (The relationship between issues) e.g. "is blocked by" or "blocks"
        issue_links = parser.jira.parse_issue_links(issue['fields'].get('issuelinks', []))

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
        label_list = match_csv_to_jira(
            issue_labels, label_sheet)

        # Getting issue priority from response
        issue_priority = issue['fields']['priority']['name']

        # Appending the issue priority to the label list as per requirement
        label_list.append(issue_priority)

        # Appending the issue owner to the label list as per requirement
        label_list.append(issue_owner)

        # Getting issue status from response
        issue_status = issue['fields']['status']['name']
        issue_closed: bool = None

        # Based on different status we set the issue status to True or False and append the status to the label list
        if issue_status == 'Reopened':
            issue_closed = False
            label_list.append('Reopened')
        elif issue_status == 'Closed':
            issue_closed = True
        elif issue_status in ['Onhold','On Hold']:
            issue_closed = True
            label_list.append('Onhold')
        elif issue_status == 'Resolved':
            issue_closed = False
            label_list.append('Resolved')
        elif issue_status == 'Open':
            issue_closed = False
        else:
            issue_closed = False
            logging.warning(f"Unknown issue status '{issue_status}' for issue {issue['key']}. Defaulting to 'Open'.")

        # Getting the type of issue from response e.g. "Bug" or "Task"
        issue_type = issue['fields']['issuetype']['name']

        # Fetching the comments from the issue
        issue_comments = endpoint.jira.fetch_all_jira_comments(
            jira_base_url, jira_user, jira_api_token, issue['key'])
        issue_xml = endpoint.jira.fetch_jira_issue_xml(jira_base_url, jira_user, jira_api_token, issue['key'])
        df_comments_media = parser.jira.parse_jira_comments_xml(issue_xml)

        # Parsing the comments to get the created date and format them
        comment_created_date = []
        formatted_comments = []
        # Formatting the comments to be added to the issue
        for comment in issue_comments:
            df_comment_medias = df_comments_media[df_comments_media.comment_id == comment["id"]].iloc[0]
            formatted_comments.append(parser.jira.format_jira_comment(comment, df_comment_medias))
            comment_created_date.append(
                date_time_helper.convert_jira_to_github_datetime_format(comment['created']))
        if issue_type == 'Bug':
            label_list.append('bug')

        comments_list = []
        for i in range(len(formatted_comments)):
            comments_list.append({
                "body": formatted_comments[i],
                "created_at": comment_created_date[i]
            })
        issue_number = endpoint.github.create_github_issue(
            github_repo, github_token, issue_title, final_description, login_user, label_list, issue_closed, issue_created, comments_list)
        github_issue_numbers.append(issue_number)

    return github_issue_numbers


def get_project_id(projects: list[dict], project_name: str) -> str:
    for project in projects:
        if project['title'] == "JAR":
            return project['id']
        else:
            raise ValueError(
                f"Project '{project_name}' not found in the list of projects.")


if __name__ == "__main__":

    JIRA_BASE_URL = os.getenv('JIRA_BASE_URL')
    JIRA_USER = os.getenv('JIRA_USER')
    JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
    GH_REPO = os.getenv('GH_REPO')
    GH_TOKEN = os.getenv('GH_TOKEN')
    PROJECT_KEY = os.getenv('PROJECT_KEY')
    JQL = os.getenv('JQL')

    logger = setup_logging()

    # Fetch Github projects that exist in working repo (Working on your own repo you can comment this out)
    projects = endpoint.github.list_projects(GH_REPO, GH_TOKEN)

    # Jar github projects to migrate to (The ones that exist in JAR Github repository)
    # ['TEST - Lokal RSjælland', 'TEST - Lokal RSyd', 'TEST - JAR-MASTER']
    projects_to = [PROJECT_KEY]

    # Function tp start the migration process
    github_issue_numbers = migrate_jira_to_github(
        JIRA_BASE_URL, JIRA_USER, JIRA_API_TOKEN, GH_REPO, GH_TOKEN, JQL, config.assignees.ASSIGNEES)

    # Add issue to project (TEST - JAR-MASTER) in GitHub
    project_id = get_project_id(projects, project_name=PROJECT_KEY)

    # Add the issues to the GitHub project
    for issue_number in github_issue_numbers:
        if issue_number:
            
            endpoint.github.add_issue_to_project(
                GH_REPO, GH_TOKEN, project_id, issue_number)

