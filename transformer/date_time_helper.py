from datetime import datetime, timezone, timedelta


def convert_jira_to_github_datetime_format(date_string: str) -> str:
    """
    Convert datetime from Jira format (2021-01-22T11:11:47.758+0100) 
    to GitHub format (2014-01-01T12:34:58Z)
    """
    try:
        # Parse the input datetime with timezone info
        if '+' in date_string:
            date_part, tz_part = date_string.split('+')
            tz_hours = int(tz_part[:2])
            tz_minutes = int(tz_part[2:]) if len(tz_part) > 2 else 0
            dt = datetime.strptime(date_part, '%Y-%m-%dT%H:%M:%S.%f')
            tz = timezone(timedelta(hours=tz_hours, minutes=tz_minutes))
            dt = dt.replace(tzinfo=tz)
            dt_utc = dt.astimezone(timezone.utc)
            return dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            # If no timezone, assume it's already in UTC
            dt = datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%f')
            return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        print(f"Error converting datetime format: {e}")
        return date_string