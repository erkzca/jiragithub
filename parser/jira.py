import logging
import xml.etree.ElementTree as ET
import os
import html
import re
from bs4 import BeautifulSoup
import pandas as pd

import config.custom_fields_to_use

# Parse Jira issue description
def parse_jira_description(description: list[str]) -> str:
    # Handle None or empty description
    if not description:
        return "No description provided"
        
    # Handle string descriptions (fallback)
    if isinstance(description, str):
        return description
        
    result = []
    
    try:
        if ('type' in description and 
            description['type'] == 'doc' and 
            'content' in description):
            for block in description['content']:
                if 'type' in block:
                    if block['type'] == 'paragraph':
                        paragraph_text = ''
                        for i, text_node in enumerate(block.get('content', [])):
                            if 'type' in text_node and text_node['type'] == 'text':
                                text = text_node.get('text', '')
                                # Handle angle brackets directly
                                #text = process_code_block(text)
                                if text == '' or (text == " " and 'marks' in text_node and text_node['marks']):
                                    continue  # Skip this node
                                 # Check if this paragraph should be treated as code
                                formatted_text = ''
                                # Checking markings
                                if 'marks' in text_node:
                                    for mark in text_node['marks']:
                                        if mark.get('type') == 'strong':
                                            formatted_text += f'**{text.strip()}**'  # Bold
                                        elif mark.get('type') == 'em':
                                            formatted_text += f'*{text.strip()}*'  # Italics
                                        elif mark.get('type') == 'link':
                                            href = mark['attrs'].get('href', '')
                                            formatted_text += f'[{text.strip()}]({href})'  # Link
                                    if formatted_text:
                                        paragraph_text += formatted_text
                                    else:
                                        paragraph_text += text  # Append plain text if no formatting was applied
                                else:
                                    paragraph_text += text  # Append plain text
                                
                                if i < len(block['content']) - 1:
                                    paragraph_text += ' '  # Add space after text if not the last node
                            elif 'type' in text_node and text_node['type'] == 'hardBreak':
                                paragraph_text += '\n'  # Add a new line for hard break
                            elif text_node['type'] == 'inlineCard':
                                url = text_node['attrs'].get('url', '')
                                paragraph_text += f' [JAR]({url})'  # Add link as markdown for inlineCard
                        if paragraph_text.startswith('<') and paragraph_text.endswith('>'):
                            result.append(f'```\n{paragraph_text.strip()}\n```\n')
                        elif paragraph_text.strip():
                            result.append(paragraph_text.strip())
                            result.append('')
                        
                    elif block['type'] == 'heading':
                        heading_text = ''
                        for text_node in block.get('content', []):
                            if 'type' in text_node and text_node['type'] == 'text':
                                heading_text += text_node.get('text', '')
                        level = block.get('attrs', {}).get('level', 1)
                        result.append('#' * level + ' ' + heading_text.strip())
                    elif block['type'] == 'rule':
                        result.append('---')  # Horizontal Rule (Markdown)
                    elif block['type'] == 'bulletList':
                        for list_item in block.get('content', []):
                            if list_item['type'] == 'listItem':
                                list_item_text = ''
                                for item_content in list_item.get('content', []):
                                    if item_content['type'] == 'paragraph':
                                        for text_node in item_content.get('content', []):
                                            if 'type' in text_node and text_node['type'] == 'text':
                                                text = text_node.get('text', '').rstrip()  # Trim right spaces
                                                if text == '' or (text == " " and 'marks' in text_node and text_node['marks']):
                                                    continue  # Skip this node
                                                formatted_text = ''
                                                # Checking for marks
                                                if 'marks' in text_node:
                                                    for mark in text_node['marks']:
                                                        if mark.get('type') == 'strong':
                                                            formatted_text += f'**{text.strip()}**'  # Bold
                                                        elif mark.get('type') == 'em':
                                                            formatted_text += f'*{text.strip()}*'  # Italics
                                                        elif mark.get('type') == 'link':
                                                            href = mark['attrs'].get('href', '')
                                                            formatted_text += f'[{text.strip()}]({href})'  # Link
                                                    list_item_text += formatted_text if formatted_text else text  # Use formatted or plain
                                                else:
                                                    list_item_text += text  # Append plain text

                                            # Handle inlineCard
                                            elif text_node['type'] == 'inlineCard':
                                                url = text_node['attrs'].get('url', '')
                                                list_item_text += f' [Link]({url})'  # Add link as markdown for inlineCard

                                if list_item_text.strip():  # Only add non-empty list items
                                    result.append(f'* {list_item_text.strip()}')  # Add bullet point
                    elif block['type'] == 'orderedList':
                        order = block.get('attrs', {}).get('order', 1)  # Get the starting order number
                        for index, list_item in enumerate(block.get('content', [])):
                            if list_item['type'] == 'listItem':
                                list_item_text = ''
                                for item_content in list_item.get('content', []):
                                    if item_content['type'] == 'paragraph':
                                        for text_node in item_content.get('content', []):
                                            if 'type' in text_node and text_node['type'] == 'text':
                                                text = text_node.get('text', '').rstrip()  # Trim right spaces
                                                if text == '' or (text == " " and 'marks' in text_node and text_node['marks']):
                                                    continue  # Skip this node
                                                formatted_text = ''
                                                # Checking for marks
                                                if 'marks' in text_node:
                                                    for mark in text_node['marks']:
                                                        if mark.get('type') == 'strong':
                                                            formatted_text += f'**{text.strip()}**'  # Bold
                                                        elif mark.get('type') == 'em':
                                                            formatted_text += f'*{text.strip()}*'  # Italics
                                                        elif mark.get('type') == 'link':
                                                            href = mark['attrs'].get('href', '')
                                                            formatted_text += f'[{text.strip()}]({href})'  # Link
                                                    list_item_text += formatted_text if formatted_text else text  # Use formatted or plain
                                                else:
                                                    list_item_text += text  # Append plain text

                                if list_item_text.strip():  # Only add non-empty list items
                                    result.append(f'{order + index}. {list_item_text.strip()}')  # Add ordered point
                    elif block['type'] == 'hardBreak':
                        result.append('\n')  # Manage hard breaks correctly
    except (AttributeError, KeyError, TypeError) as e:
        logging.error(f"Error parsing description: {e}")
        return "Error parsing description"
        
    return '\n'.join(result) if result else "No description found"

def adf_table_to_markdown(block) -> str:
    """
    Convert a Jira ADF `table` block to GitHub-flavoured Markdown.
    """
    def cell_text(cell):
        out = []
        for paragraph in cell.get('content', []):
            if paragraph['type'] == 'paragraph':
                for item in paragraph.get('content', []):
                    process_content(item, out)          # ← already exists
        return ''.join(out).strip()

    rows = [
        [cell_text(c) for c in row.get('content', [])]
        for row in block.get('content', [])
    ]
    if not rows:
        return ''

    header, *body = rows
    md = [
        '| ' + ' | '.join(header) + ' |',
        '| ' + ' | '.join(['---'] * len(header)) + ' |',
    ]
    md += ['| ' + ' | '.join(r) + ' |' for r in body or [[]]]
    return '\n'.join(md)

def html_table_to_markdown(table: BeautifulSoup) -> str:
    """
    Convert a BeautifulSoup <table> element into a GitHub-flavored markdown table.
    """
    rows = []
    for tr in table.find_all('tr'):
        cells = tr.find_all(['th', 'td'])
        rows.append([cell.get_text(strip=True) for cell in cells])

    if not rows:
        return ''  # empty table

    # Header row and separator
    header = rows[0]
    separator = ['---'] * len(header)

    md_lines = []
    md_lines.append('| ' + ' | '.join(header) + ' |')
    md_lines.append('| ' + ' | '.join(separator) + ' |')

    # Data rows
    for row in rows[1:]:
        # pad short rows if necessary
        if len(row) < len(header):
            row += [''] * (len(header) - len(row))
        md_lines.append('| ' + ' | '.join(row) + ' |')

    return '\n'.join(md_lines)


def parse_jira_comments_xml(xml: str) -> pd.DataFrame:
    """
    Parse Jira comments from XML into a DataFrame, extracting text, media/file attachments, and tables.
    """
    root = ET.fromstring(xml)

    # Build a mapping of attachment ID to filename
    attachments = {att.get('id'): att.get('name') for att in root.findall('.//attachments/attachment')}

    rows = []
    for c in root.findall('.//comment'):
        raw_html = html.unescape(c.text or '')
        soup = BeautifulSoup(raw_html, 'html.parser')

        # 1) Image attachments: <img src=...> and Jira thumbnail wrappers
        img_srcs, img_names = [], []
        # a) standard <img src> tags (skip icon images)
        for img in soup.find_all('img', src=True):
            src = img['src']
            if '/images/icons/' in src:
                continue
            img_srcs.append(src)
            m = re.search(r'/attachment/content/(\d+)', src)
            img_names.append(attachments.get(m.group(1), 'NO_FILE_NAME') if m else 'NO_FILE_NAME')
        # b) <a file-preview-type="image"> wrappers
        for a in soup.find_all('a', attrs={'file-preview-type': 'image'}, href=True):
            src = a['href']
            if src in img_srcs:
                continue
            img_srcs.append(src)
            # pick a name from attributes or fallback
            name = (
                a.get('file-preview-title')
                or a.get('data-attachment-name')
                or a.get('title')
                or attachments.get(re.search(r'/attachment/content/(\d+)', src).group(1), '')
            )
            img_names.append(name or 'NO_FILE_NAME')

        # 2) File attachments
        file_links, file_names = [], []
        for a in soup.find_all('a', href=True):
            m = re.search(r'/attachment/content/(\d+)', a['href'])
            if m and a.get('data-attachment-type') == 'file':
                fid = m.group(1)
                file_links.append(a['href'])
                file_names.append(
                    a.get('data-attachment-name')
                    or attachments.get(fid)
                    or a.get_text(strip=True)
                )

        # Combine media lists
        media_srcs = img_srcs + file_links
        media_names = img_names + file_names
        media_types = ['image'] * len(img_srcs) + ['file'] * len(file_links)

        # 3) Tables to markdown
        tables_md = [html_table_to_markdown(tbl) for tbl in soup.find_all('table')]

        rows.append({
            'comment_id': c.get('id'),
            'author': c.get('author'),
            'created': c.get('created'),
            'text': soup.get_text(' ', strip=True),
            'media_srcs': media_srcs,
            'media_names': media_names,
            'media_types': media_types,
            'tables': tables_md,
        })

    return pd.DataFrame(rows, columns=[
        'comment_id', 'author', 'created', 'text',
        'media_srcs', 'media_names', 'media_types', 'tables'
    ])

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


def format_jira_comment(comment: dict, media_record: list[str]):

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
    idx = 0

    # img_names = df_media_comments.img_names # .iloc[media_number,:]
    # img_srcs = df_media_comments.img_srcs

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
        # IMAGE or FILE → treat them the same: drop a Markdown link right here
        elif block['type'] in ('mediaSingle', 'mediaInline', 'mediaGroup'):
            # `mediaGroup` can hold several <media> nodes
            for _ in range(1 if block['type'] != 'mediaGroup' else len(block.get('content', []))):
                if idx >= len(media_record['media_srcs']):
                    break            # safety-net - nothing left to emit

                src  = media_record['media_srcs'][idx]
                name = media_record['media_names'][idx]

                # Jira thumbnails → content endpoint
                if 'thumbnail' in src:
                    src = src.replace('https://jar-cowi.atlassian.net/', '')
                    src = src.replace('thumbnail', 'content')

                # Ensure absolute URL
                if src.startswith('/'):
                    src = f'{JIRA_BASE_URL}{src}'

                formatted_parts.append(f'[{name}]({src})')
                idx += 1

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
        elif block['type'] == 'table':
            md = adf_table_to_markdown(block)
            if md:
                formatted_parts.append(md)
        elif block['type'] == 'codeBlock':
            # new handler for code blocks
            language = block.get('attrs', {}).get('language', '')
            # join all text nodes in content
            code_lines = []
            for item in block.get('content', []):
                if item.get('type') == 'text':
                    code_lines.append(item.get('text', ''))
            code_text = '\n'.join(code_lines)
            # emit a fenced code block with optional language
            fence = f"```{language}" if language else "```"
            formatted_parts.append(f"{fence}\n{code_text}\n```")

    # for table_md in media_record.get('tables', []):
    #     formatted_parts.append(table_md)
    
    # Final formatted output
    return '\n'.join(formatted_parts)