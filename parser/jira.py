import logging

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