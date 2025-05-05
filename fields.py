import requests
from requests.auth import HTTPBasicAuth
import pandas as pd





def fetch_jira_labels(jira_url, jira_user, jira_api_token):
    url = f'{jira_url}'
    response = requests.get(url, headers={'Accept': 'application/json'},
                            auth=HTTPBasicAuth(jira_user, jira_api_token))
    if response.status_code == 200:
        return response.json()
    else:
        print("Failed to fetch labels:", response.status_code, response.text)
        exit()


url = 'https://jar-cowi.atlassian.net/rest/api/3/field'
username = ''
jira_api_token = ''

jira_labels = fetch_jira_labels(url, username, jira_api_token)
print(jira_labels)




