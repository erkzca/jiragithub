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
                inward_summary = inward_issue.get(
                    "fields", {}).get("summary", "")
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
                outward_summary = outward_issue.get(
                    "fields", {}).get("summary", "")
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
            # Include the relationship as a heading
            output.append(f"{relationship}:")
            # Add the links below the relationship heading
            output.extend(links)
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
        logging.error("Failed to fetch comments for issue:",
                      issue_key, response.status_code, response.text)
        return []
    
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
                                # Add space between texts
                                text_content += paragraph['text'] + " "
                if text_content.strip():  # Check if there's any extracted text
                    formatted_fields.append(
                        f"{field_name}: {text_content.strip()}")
            # If it's not a dict, handle other types as necessary (e.g., string)
            elif isinstance(value, str) or value:
                formatted_fields.append(f"{field_name}: {value}")
    result_string = "\n".join(formatted_fields)
    if not result_string:
        return []
    else:
        return "\n ## Brugerdefineret felt\n" + result_string


def _wrap(text: str, marker: str) -> str:
    """
    Wrap only the 'core' of the text in marker, preserving whitespace.
    e.g. _wrap("  foo  ", "*") -> "  *foo*  "
    """
    _WS_RE = re.compile(r'^(\s*)(.*?)(\s*)$', re.DOTALL)

    lead, core, trail = _WS_RE.match(text).groups()
    if not core:
        return text
    return f"{lead}{marker}{core}{marker}{trail}"

def process_content(item, output):
    """Helper to convert a single ADF node to GitHub-flavored Markdown."""
    t = item.get('type')

    if t == 'mention':
        # strip leading '@', preserve trailing space
        name = item['attrs']['text'].lstrip('@')
        output.append(f"{name} ") # not using "@" because it takes github users not part of the repo

    elif t == 'text':
        txt = item['text']
        # strip any stray @ in plain text
        txt = re.sub(r'@(\w+)', r'\1', txt)

        if item.get('marks'):
            # detect which marks are present
            marks = {m['type']: m for m in item['marks']}
            # apply in nesting order: bold → italic → underline → link
            if 'strong' in marks:
                txt = _wrap(txt, '**')
            if 'em' in marks:
                txt = _wrap(txt, '*')
            if 'underline' in marks:
                # HTML underline is fine for GFM
                txt = f"<ins>{txt}</ins>"
            if 'link' in marks:
                href = marks['link']['attrs']['href']
                txt = f"[{txt}]({href})"

        output.append(txt)

    elif t == 'hardBreak':
        output.append('\n')

    elif t == 'inlineCard':
        url = item['attrs'].get('url', '')
        output.append(f"[Link]({url})")

    elif t == 'emoji':
        output.append(item['attrs'].get('text', ''))
    
    elif t == 'mediaInline':
        logging.info("type 'mediaInline' not implemented: %s", item)

    else:
        # you can expand for paragraphs, lists, etc.
        raise NotImplementedError(f"Unsupported node type: {t}")


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


def format_jira_comment(comment: dict, df_media_comments: list[str]):

    JIRA_BASE_URL = os.getenv('JIRA_BASE_URL')
    
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
    media_number = 0

    img_names = df_media_comments.img_names # .iloc[media_number,:]
    img_srcs = df_media_comments.img_srcs

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
        elif block['type'] == 'mediaSingle':

            img_name = img_names[media_number]
            img_src = img_srcs[media_number]

            if 'thumbnail' in img_src:

                img_src = img_src.replace('https://jar-cowi.atlassian.net/', '')
                img_src = img_src.replace('thumbnail', 'content')

            formatted_parts.append(f'[{img_name}]({JIRA_BASE_URL}/{img_src})')
            media_number += 1

        elif block['type'] == 'blockquote' and 'content' in block:
            # Start blockquote with markdown indicator
            blockquote_text = ["> "]

            for paragraph in block['content']:
                if paragraph['type'] == 'orderedList' and 'content' in paragraph:
                    for index, list_item in enumerate(paragraph['content'], start=paragraph['attrs'].get('order', 1)):
                        list_item_text = []
                        # Use index for ordered number
                        list_item_text.append(f"{index}. ")

                        for item in list_item['content']:
                            if 'content' in item:
                                for par in item['content']:
                                    process_content(par, list_item_text)

                        formatted_text = ''.join(list_item_text).strip()
                        if formatted_text:
                            blockquote_text.append(formatted_text)
                    # New line after list in blockquote
                    blockquote_text.append('\n')

                elif paragraph['type'] == 'paragraph' and 'content' in paragraph:
                    for item in paragraph['content']:
                        process_content(item, blockquote_text)
                    # New line for each paragraph in blockquote
                    blockquote_text.append('\n')

            formatted_text = ''.join(blockquote_text).strip()
            if formatted_text:
                # Append the formatted blockquote
                formatted_parts.append(formatted_text)
            # Adding an empty line after the blockquote
            formatted_parts.append('')

        elif block['type'] == 'orderedList' and 'content' in block:
            # Use helper function for ordered lists
            format_ordered_list(block, formatted_parts)
        elif block['type'] == 'bulletList' and 'content' in block:
            format_bullet_list(block, formatted_parts)

    # Final formatted output
    return '\n'.join(formatted_parts)